# PropertyLedger Guided Workflow Test

Use this guide to exercise the implemented WP1–WP6 workflows in a disposable local environment. It is designed for a tester working through the product in a browser while a moderator records evidence.

The fixture pack contains synthetic data only. The reset command deletes both local Docker databases. Never run it against bookkeeping data you need to retain.

## Prepare the environment

From the PropertyLedger repository root:

```bash
bash scripts/beta-reset.sh
bash scripts/beta-seed.sh
```

Start LedgerOS and PropertyLedger:

```bash
cd ../ledgeros_v2 && WEB_PORT=8001 make up
cd ../propertyledger && make up
make smoke
bash scripts/workflow-test-status.sh
```

The status script is read-only. It confirms the fixture pack and prints current workflow states plus the release compatibility inventory. Open PropertyLedger at `http://localhost:8000/home/` and LedgerOS at `http://localhost:8001/`.

All demo users use password `PropertyLedgerBeta123!`.

| User | Role and intended test |
| --- | --- |
| `beta-admin` | Setup, audit log, authorizations, and unrestricted review |
| `beta-manager` | Maintenance lifecycle and independent bill approval |
| `beta-bookkeeper` | Charges, receipts, bill submission/posting, and authorized payment |
| `beta-owner-viewer` | Owner/reporting visibility without writes |
| `beta-read-only` | General read access without writes |

## Demo records to use

Use **Cedar Grove Apartments**, owned by **Cedar Grove Holdings LLC**. Find the records below by tenant, amount, unit, or maintenance description. Codes beginning with `BETA-` are test-data references, not values you need to enter.

| Scenario | Record to look for | Initial state |
| --- | --- | --- |
| Vendor provisioning | Ace Plumbing, Bright Electric, GreenLine Landscaping | Local vendor records; fresh seeding does not sync them to LedgerOS |
| Tenant provisioning | Avery Jordan | Local tenant record; explicitly provision the matching LedgerOS customer before posting rent in step 5 |
| Rent and deposit | Avery Jordan’s $1,950.00 rent and security-deposit receipt, unit 101 | Draft receipt for `1950.00`: rent `1450.00`, deposit `500.00`; no allocations posted |
| Maintenance lifecycle | the unit 101 request, “Kitchen sink is leaking into the cabinet.” | Urgent leaking sink request, Open |
| Hold and resume | the unit 102 request, “Hallway light flickers intermittently.” | Hallway light request, On hold while awaiting access |
| Maintenance bill handoff | the unit 103 request, “Remove fallen branches and restore the rear walkway.” | Closed and verified; vendor invoice pending; no linked bill |
| Approved payable | Ace Plumbing bill for `240.00` | Approved locally; sync the vendor before posting the bill to LedgerOS |
| Approval queue | Bright Electric bill for `180.00` | Submitted by the bookkeeper; awaiting independent approval |
| Draft payable | GreenLine Landscaping bill for `315.00`, “Monthly landscaping service” | Draft, with no unit selected; prepare it for linking in step 3 |

The seed is idempotent before workflow execution. Once a tester changes or posts a scenario, use `beta-reset.sh` followed by `beta-seed.sh` to restore its documented initial state. Rerunning the seed does not reverse lifecycle or accounting activity.

## 1. Home, navigation, and role boundaries

1. Sign in as `beta-admin` and open `/home/`.
2. Confirm the three workflow cards lead to receipts, vendor payables, and maintenance.
3. Confirm Setup reports a selected LedgerOS entity, open period, and healthy connection.
4. Resize to a narrow viewport. Open and close the navigation drawer with the keyboard; Escape should close it and return focus to Menu.
5. Sign in as `beta-read-only`. Open receipts, bills, maintenance, and reports.
6. Confirm create, approve, pay, sync, edit, archive, and lifecycle controls are absent or denied.
7. Repeat with `beta-owner-viewer`; confirm reporting access and no financial write controls.

Record the role, URL, visible action, attempted forbidden action, HTTP result, and screenshot. A read-only POST must be denied before any LedgerOS request or local accounting-state change.

## 2. Maintenance lifecycle

Sign in as `beta-manager` and open the maintenance queue.

1. Open the unit 101 request, “Kitchen sink is leaking into the cabinet.” and confirm Cedar Grove, unit 101, Avery Jordan, Plumbing, Ace Plumbing, urgent priority, and `240.00` estimate.
2. Move it through Triage, Assign, Start, and Verify.
3. Close it with **Vendor invoice pending** and a meaningful closure note.
4. Confirm the event history records each actor, old state, new state, reason, and version.
5. Reopen it with a reason. Confirm the prior close event remains and the reopen count increases.
6. Open the unit 102 request, “Hallway light flickers intermittently.”, resume it, and confirm it returns to its prior Triaged state.

Expected accounting result: none. Maintenance transitions must not create a bill, payment, journal, tenant-ledger line, owner-statement line, sync record, or LedgerOS mutation.

## 3. Maintenance-to-vendor-bill handoff

Sign in as `beta-bookkeeper`. This scenario demonstrates a linking dependency: a bill must belong to the same property and, for a unit-specific maintenance request, the same unit. The existing **GreenLine Landscaping $315.00 draft bill** starts with no unit selected and the description **Monthly landscaping service**.

1. Open the unit 103 maintenance request, “Remove fallen branches and restore the rear walkway.” Under **Link an existing bill**, notice that the GreenLine bill is absent. It exists, but its unit does not match the request.
2. Open **Vendor Bills**, find the existing GreenLine Landscaping $315.00 draft, and choose **Edit**.
3. For this demo, treat that draft as the invoice for the walkway repair. Keep **Cedar Grove Apartments**, select unit **103**, change the repair description to **Remove fallen branches and restore the rear walkway.**, and choose **Save draft**. In actual use, only change attribution when it matches the vendor invoice and work performed.
4. Return to the maintenance request. Under **Link an existing bill**, select the GreenLine Landscaping $315.00 bill and choose **Link bill**. No new bill is needed.
5. Confirm the bill appears once in the linked-bills table and the request remains Closed with Vendor invoice pending.
6. Open the linked bill and confirm it links back to the request. Approval and posting should remain in their draft states; linking does not approve, post, or pay it.

Property managers can link compatible existing bills, but editing this draft requires a bookkeeper or administrator. If the bill already has the matching unit and description from an earlier walkthrough, skip the edit. If it is already linked, review the existing link instead of creating another bill.

Expected accounting result: none until the bill is separately approved and posted. Maintenance closure must remain independent from bill approval, posting, and payment.

## 4. Bill approval, posting, and payment

1. Sign in as `beta-manager` and open the approval queue.
2. Approve the submitted Bright Electric `180.00` bill. Confirm the original bookkeeper submitter cannot approve it.
3. Sign in as `beta-bookkeeper`. Open **Vendors** and check **Ace Plumbing** in the **LedgerOS status** column. Fresh demo data shows **Not synced**. Choose **Sync to LedgerOS**, then confirm **Synced** and a last successful sync time. If it fails, follow the displayed guidance and choose **Retry sync** for the same vendor. If already Synced, continue to the bill; no vendor edits are required.
4. Open the approved Ace Plumbing `240.00` bill.
5. Post the bill to LedgerOS and confirm the local state shows a successful bill resource/reference.
6. Choose **Pay bill** on that bill, enter `100.00`, review the payment date, choose the payment method, and retain the configured **Operating Bank** account for non-card payments. Choose **Post payment**. Confirm **Payment posted to LedgerOS.** and a remaining payable of `140.00`. If the form returns with **Payment could not be completed**, read the error summary, correct the indicated fields, and submit the same form again. The balance remains `240.00` until LedgerOS confirms the payment.
7. Submit the same payment again only as a replay check. Confirm one local payment and one LedgerOS accounting effect.
8. Record the remaining `140.00`. Confirm the bill is fully paid and a new payment action is no longer offered.

The seed creates vendors locally without provisioning them in LedgerOS. Setup smoke passing and a bill's local approval do not imply its vendor is synced. Check vendor sync status and sync Bright Electric or GreenLine Landscaping before posting their bills. Vendor provisioning does not post a bill or payment.

Expected accounting behavior: approval itself creates no ledger entry. Bill posting records the expense/payable once. Payments reduce the payable without changing the original expense, owner expense total, or tenant ledger. Every retry retains the same local payment and idempotency identity.

### Withdraw an approved bill before posting

While creating the test bill below, open bill entry from the bill list and choose **Save and submit for approval**. Confirm the list returns with a success message that can be closed with its red X and disappears automatically after 10 seconds. Repeat from a maintenance request and confirm it returns to the request with the linked submitted bill. An invalid form should retain its original return page after correction; **Save draft** should continue to open bill detail.

Before continuing, test approved-bill withdrawal on a separate unposted bill:

1. As `beta-bookkeeper`, save and submit a new bill. As `beta-manager`, approve it.
2. As the submitter, open the bill and choose **Withdraw approved bill** with a reason. Confirm a blank reason is rejected, then enter a reason and withdraw.
3. Confirm Withdrawn status, preserved approval and withdrawal history, and no posting/payment action. No sync record, LedgerOS bill, journal, balance, or report change should result.
4. Resubmit the same bill and independently approve it again. Confirm posting becomes available again.
5. Confirm another bookkeeper cannot withdraw this bill; an administrator can withdraw an eligible bill submitted by someone else. Once a bill has a posting attempt (including failure/timeout), approved withdrawal must be unavailable. Recover that attempt on the same bill.

## 5. Combined rent and security-deposit receipt

**Prerequisite: explicitly provision the tenant customer.** The seed creates Avery Jordan locally but does not provision a LedgerOS customer. A healthy setup smoke check does not confirm that the customer exists.

1. Sign in as `beta-admin` or `beta-manager` and open **Tenants**.
2. Choose **View** for Avery Jordan, then **Provision in LedgerOS**.
3. Review the tenant name, customer code, and default AR account. Choose **Provision in LedgerOS** on the review page to submit the request.
4. Confirm **Tenant customer provisioned in LedgerOS.** This creates a missing customer or verifies an exact match; it does not update a conflicting customer or post an invoice, receipt, or journal. If a conflict is reported, have an administrator review the customer mapping before continuing.

This requires LedgerOS's strict `/api/v1/customers/provision/` endpoint. Deploy the matching LedgerOS change before testing; there is no fallback to customer upsert. No migration is required. An unavailable endpoint, missing permission, or failed provisioning blocks this scenario until resolved.

If posting previously failed with `customer_code: Unknown customer.`, the invoice's sync log provides recovery guidance. Admins and property managers can follow **Review tenant provisioning**; bookkeepers must ask one of those users to perform provisioning. After confirmed provisioning, open the same failed invoice with **View** and choose **Approve and post to LedgerOS** in **LedgerOS Sync**. Provisioning does not retry the invoice, so its historical failure warning remains until a successful retry. The warning describes the last attempt rather than the current LedgerOS customer state; **Review invoice and post** in the list opens that invoice for an explicit retry. Keep the original charge and receipt so their sync identities are preserved. **Save tenant** only saves local edits; neither tenant edits nor charge approval run provisioning.

Sign in as `beta-bookkeeper`.

1. Open Avery Jordan's current `1450.00` base-rent charge with **View**. In **LedgerOS Sync**, choose **Approve and post to LedgerOS** and confirm **Invoice posted to LedgerOS.** The Edit screen offers the same action for the saved invoice; save edits first. Confirm a failed attempt shows its error and retains the action for retry, while a successfully posted invoice shows its sync reference and no posting button.
2. Open tenant receipts and select Avery Jordan’s draft receipt for **$1,950.00** ($1,450.00 rent plus $500.00 security deposit).
3. Confirm total `1950.00`, rent portion `1450.00`, and deposit portion `500.00` tied to Avery's unit 101 lease.
4. Auto-allocate the rent portion and review the component status before finalization.
5. Finalize the same receipt.
6. Confirm the invoice application and deposit journal each have their own successful reference and the parent receipt is Posted.
7. Retry finalization and confirm no additional payment, sync event, or journal appears.

Expected aggregate LedgerOS result:

- Cash increases `1950.00` exactly once.
- Accounts receivable decreases `1450.00`.
- Tenant security deposit liability increases `500.00`.
- Rent and owner reporting include only the confirmed `1450.00` rent component.
- Deposit reporting includes only the confirmed `500.00` liability component.

Do not create a replacement receipt after a timeout. Retry the same receipt so its frozen payloads and idempotency identities are reused.

## 6. Reports and history

After the accounting scenarios succeed:

1. Open Avery Jordan's tenant ledger. Confirm the rent charge and `1450.00` confirmed rent receipt; the `500.00` deposit must not appear as rent.
2. Open the Cedar Grove property and owner reports. Confirm the posted bill expense is present once and partial/full payments do not duplicate it.
3. Open security-deposit reporting and confirm the `500.00` receipt component appears as deposit activity.
4. Open the audit log and verify the maintenance, approval, posting, and payment actors.

Treat an upstream-derived value as **Unavailable** during a read failure. A zero value is not an acceptable substitute.

## 7. LedgerOS outage and recovery

Use the same browser records so identity preservation is visible.

1. Stop only the LedgerOS web service from the sibling repository:

   ```bash
   cd ../ledgeros_v2
   docker compose stop web
   ```

2. Reload PropertyLedger `/home/`. Confirm the LedgerOS unavailable warning and **Unavailable** accounting values.
3. As `beta-manager`, create or update a local maintenance request. It must succeed.
4. As `beta-bookkeeper`, save a new receipt draft and a vendor-bill draft. They must succeed.
5. Attempt to finalize the receipt, post the bill, and pay an eligible bill. Each action must stop before a new sync attempt.
6. Record the local object IDs and current sync-attempt counts.
7. Restart LedgerOS and rerun readiness:

   ```bash
   cd ../ledgeros_v2
   WEB_PORT=8001 docker compose up -d web
   cd ../propertyledger
   make smoke
   ```

8. Retry each blocked action on the same local record. Confirm IDs are unchanged, attempts resume safely, and no duplicate accounting effects appear.

There is no automatic offline accounting queue. Recovery requires an explicit retry of the preserved record.

## Capture results

For every scenario, record:

- tester and role;
- timestamp and application commit;
- local record ID and status before/after;
- LedgerOS resource/journal IDs where applicable;
- relevant balances or report totals before/after;
- retry count and duplicate-count check;
- screenshot or error text;
- Pass, Fail, or Blocked with notes.

After testing, run:

```bash
bash scripts/workflow-test-status.sh
make release-check
```

Keep the output with the screenshots. A production release still requires a prepared non-production LedgerOS acceptance environment, explicit workflow grants, reviewed account mappings, and a rollback plan that disables financial writes while preserving all rows and IDs.
