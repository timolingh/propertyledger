# PropertyLedger Guided Workflow Test

Use this guide to exercise the implemented WP1–WP6 workflows in a disposable local environment. It is designed for a tester working through the product in a browser while a moderator records evidence.

The seed supplies setup, roles, and separate records for later exercises. The first walkthrough creates its own tenant and transaction history from scratch. All demo data is synthetic. The reset command deletes both local Docker databases. Never run it against bookkeeping data you need to retain.

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

## Start here: a new tenant’s first payment

Complete sections 1–6 before opening the prepared scenarios later in this guide. Use the existing **Cedar Grove Apartments** property and owner as setup prerequisites, but create a **new tenant, unit, lease, invoice, and receipt** yourself. Do not use Avery’s prepared receipt or deposit events for this first walkthrough.

The story: **Dana Morgan moves into unit 104. Monthly rent is \$1,450 and the required refundable deposit is \$1,450. Dana pays both in full with one \$2,900 check.** No receipt exists until the tester records that check.

Use dates within the configured open LedgerOS period. The examples below use November 2026: lease/rent start **November 1**, rent due **November 1**, and payment received **November 6**. If the demo uses a different month, agree on equivalent dates before starting.

## 1. Create the tenant

Sign in as **beta-manager**.

1. Open **Tenants → Add tenant**.
2. Enter **Dana Morgan**, email **dana.morgan@example.test**, and leave the tenant active. Phone and notes are optional.
3. Choose **Create tenant**. This creation flow also provisions the LedgerOS customer. Confirm **Tenant created and provisioned in LedgerOS** and Dana’s **Synced** badge, then choose **View**. If creation fails, resolve the reported setup or connection problem before continuing.
4. Confirm the name and contact information you just entered.

**Checkpoint:** Dana now exists in PropertyLedger. No lease, invoice, receipt, or payment has been created for Dana. If Dana already exists from an earlier run, use a fresh tenant name and unused unit for this walkthrough rather than mixing histories.

## 2. Verify the tenant’s LedgerOS connection

Stay signed in as **beta-manager**. If Dana’s list row already shows **Synced**, creation completed provisioning; continue to section 3. For a tenant showing **Not confirmed**, **Sync failed**, or **Needs review**, follow this recovery path:

1. Choose **Provision in LedgerOS**.
2. On the review page, confirm **Dana Morgan**, the generated customer code, and the configured default Accounts Receivable account. Do not enter or guess a customer code.
3. Choose **Provision in LedgerOS** to confirm.
4. Confirm **Tenant customer provisioned in LedgerOS.** Stop here if it fails; resolve the reported setup or customer conflict before proceeding.

**Checkpoint:** LedgerOS can now accept invoices for Dana. Provisioning creates or verifies the customer; it does not create charges or move money. Creating a tenant provisions the customer; editing an existing tenant does not automatically provision it.

## 3. Create the unit and lease

Stay signed in as **beta-manager**.

1. Open **Units → Add unit**. Select **Cedar Grove Apartments**, name the unit **104**, keep it active, and choose **Create unit**. Use another unused unit name if 104 already exists.
2. Open **Leases → Add lease** and enter:

   | Field | Value |
   | --- | --- |
   | Unit | Cedar Grove Apartments / 104 |
   | Tenant | Dana Morgan |
   | Lease start date | November 1, 2026 |
   | Lease end date | Leave blank |
   | Rent effective date | November 1, 2026 |
   | Base monthly rent amount | \$1,450.00 |
   | Deposit required amount | \$1,450.00 |
   | Status | Active |

3. Choose **Create lease**, then open it with **View**. Confirm tenant, unit, rent, and deposit requirement.
4. Open **Security Deposits** and find Dana’s lease. Confirm **Required by lease \$1,450**, **Confirmed received \$0**, and **Remaining to collect \$1,450**. There should be no deposit activity for Dana yet.

**Checkpoint:** The deposit obligation is introduced here, on the lease. A lease is local property-management data and has no separate LedgerOS sync button. It does not prove any money has been received.

## 4. Create and post the rent invoice

Sign in as **beta-bookkeeper**.

1. Open **Invoices → Add invoice**.
2. Select Dana’s new lease. It determines the property, unit, and tenant.
3. Choose **Base rent**, enter **\$1,450.00**, and describe it as **November rent — unit 104**. Set the billing period to **November 1–30, 2026**, the charge date to **November 1**, and the due date to **November 1**. Leave status **Draft**.
4. Choose **Create invoice**, then **View** that new invoice in the list. Confirm Dana, unit 104, and \$1,450 before posting.
5. In **LedgerOS Sync**, choose **Approve and post to LedgerOS**. Confirm **Invoice posted to LedgerOS** and **Synced** status. A failed attempt must be recovered on this same invoice; do not create a replacement.

**Checkpoint:** The invoice records rent owed, not rent paid. The deposit obligation remains separate on the lease.

| Dana owes before payment | Amount |
| --- | ---: |
| Rent invoice | \$1,450.00 |
| Required deposit | \$1,450.00 |
| **Total** | **\$2,900.00** |

## 5. Receive the check and create the receipt

Stay signed in as **beta-bookkeeper**. **Now simulate Dana handing you a \$2,900 check for the full rent and full deposit.** This is the first payment event in the story; PropertyLedger does not collect money itself.

1. Open **Home → Record rent / deposit receipt**. Use this combined-receipt form for the check covering both rent and deposit.
2. Enter the payment yourself:

   | Field | Value |
   | --- | --- |
   | Property | Cedar Grove Apartments |
   | Tenant | Dana Morgan |
   | Payment date | November 6, 2026 |
   | Amount | **\$2,900.00**, the entire check |
   | Payment method | Check |
   | Reference | Dana first payment — check 1041 |
   | Notes | First month’s rent and full security deposit |
   | Deposit amount | **\$1,450.00**, the part of this check for the deposit |
   | Deposit lease | Dana’s unit 104 lease |

3. On this same form, confirm the waterfall defaults to **Open invoices 1,450.00**, **Deposit 1,450.00**, **Other 0.00**, with zero remaining. Open invoices include late fees and are paid oldest first. Selecting the deposit lease caps its allocation at the remaining requirement.
4. Choose **Save receipt for review**. This saves the reviewed allocation without posting. On the receipt, confirm total **2,900.00**, invoice allocations **1,450.00**, deposit **1,450.00**, Other **0.00**, and unapplied **0.00**. The component references must not yet claim posted money.
5. Choose **Post receipt to LedgerOS**. Confirm **Posted** status and separate confirmed invoice-payment and deposit-journal references. Repeating the action must create no additional payment or journal.
6. On a separate unposted receipt, use **Review receipt allocation** to test overrides. Enter **0** for invoices: funds must flow to deposit, then Other. Enter **0** for deposit: funds must flow to Other. Positive Other requires an account code. Save, reopen, and confirm the zeros and credited account remain. Restore the intended split before posting. A partially assigned draft can save but cannot post; excessive invoice/deposit allocations must be rejected without a journal.

**Checkpoint:** One check has been recorded through one receipt. Do not also create a standalone “Deposit received” event for this money.

### If you recorded the check from the invoice instead

New invoice entry uses **Record receipt and review allocation**, opening the same waterfall form with the invoice's property and tenant. Enter the full check amount there and follow the same review/save/post steps. Creating an invoice receipt no longer requires posting rent before reviewing the deposit split.

Do not enter the check again. On the invoice’s **Applied Payments** table, choose **Assign to security deposit** beside the existing payment’s unapplied balance. On its receipt page, select Dana’s unit 104 lease and enter **\$1,450** as the deposit amount, then choose **Assign to security deposit**. Confirm total \$2,900, rent applied \$1,450, deposit assigned \$1,450, and unapplied balance \$0. Choose **Post receipt to LedgerOS**. The rent payment already posted is retained and is not posted again.

## 6. Verify the completed first-payment story

1. Return to Dana’s rent invoice. Confirm the \$1,450 payment application; the invoice balance should be zero on the open-invoice/payment view.
2. Open **Tenant Receipts**. Find the receipt you created: total **\$2,900**, rent applied **\$1,450**, deposit assigned **\$1,450**, nothing left to apply, and **Posted** status.
3. Open **Security Deposits**. Dana’s lease should show **\$1,450 required**, **\$1,450 confirmed received**, **\$0 remaining**, and no excess. Its \$1,450 deposit activity must link back to the receipt you created.
4. Review Dana’s tenant ledger and deposit report. The rent payment is \$1,450; the other \$1,450 belongs to deposit activity, not rent income or rent receivables.

| Component | Owed before payment | Received and posted | Still to collect |
| --- | ---: | ---: | ---: |
| Rent | \$1,450.00 | \$1,450.00 | \$0.00 |
| Deposit | \$1,450.00 | \$1,450.00 | \$0.00 |
| **Total** | **\$2,900.00** | **\$2,900.00** | **\$0.00** |

For the moderator’s accounting check, the receipt increases Cash by \$2,900, reduces rent AR by \$1,450, and increases the deposit liability by \$1,450. Its parent receipt does not post the cash again. Provisioning and lease creation create no journals. Preserve the record IDs for any retry checks.

Only move on when the tester can explain where the obligation came from, when money arrived, what was entered, and which actions posted it.

## Prepared records for later scenarios

These records are deliberately prefilled or partially complete. Use them only after the new-tenant walkthrough above. They belong to separate scenarios and must not be mixed with Dana’s payment.

Use **Cedar Grove Apartments**, owned by **Cedar Grove Holdings LLC**. Find the records below by tenant, amount, unit, or maintenance description. Codes beginning with `BETA-` are test-data references, not values you need to enter.

| Scenario | Record to look for | Initial state |
| --- | --- | --- |
| Vendor provisioning | Ace Plumbing, Bright Electric, GreenLine Landscaping | Local vendor records; fresh seeding does not sync them to LedgerOS |
| Tenant provisioning | Avery Jordan | Local tenant record; explicitly provision the matching LedgerOS customer before posting rent in section 11 |
| Rent and deposit | Avery Jordan’s unit 101 lease, \$1,450.00 rent invoice, and \$1,950.00 draft receipt | Lease requires a \$1,450.00 deposit separately from rent. The draft receipt is a prepared example for a simulated check: \$1,450.00 rent plus \$500.00 partial deposit; no payment has been posted |
| Maintenance lifecycle | the unit 101 request, “Kitchen sink is leaking into the cabinet.” | Urgent leaking sink request, Open |
| Hold and resume | the unit 102 request, “Hallway light flickers intermittently.” | Hallway light request, On hold while awaiting access |
| Maintenance bill handoff | the unit 103 request, “Remove fallen branches and restore the rear walkway.” | Closed and verified; vendor invoice pending; no linked bill |
| Approved payable | Ace Plumbing bill for `240.00` | Approved locally; sync the vendor before posting the bill to LedgerOS |
| Approval queue | Bright Electric bill for `180.00` | Submitted by the bookkeeper; awaiting independent approval |
| Draft payable | GreenLine Landscaping bill for `315.00`, “Monthly landscaping service” | Draft, with no unit selected; prepare it for linking in section 9 |

The seed is idempotent before workflow execution. Once a tester changes or posts a scenario, use `beta-reset.sh` followed by `beta-seed.sh` to restore its documented initial state. Rerunning the seed does not reverse lifecycle or accounting activity.

## 7. Home, navigation, and role boundaries

1. Sign in as `beta-admin` and open `/home/`.
2. Confirm the three workflow cards lead to receipts, vendor payables, and maintenance.
3. Confirm Setup reports a selected LedgerOS entity, open period, and healthy connection.
4. Resize to a narrow viewport. Open and close the navigation drawer with the keyboard; Escape should close it and return focus to Menu.
5. Sign in as `beta-read-only`. Open receipts, bills, maintenance, and reports.
6. Confirm create, approve, pay, sync, edit, archive, and lifecycle controls are absent or denied.
7. Repeat with `beta-owner-viewer`; confirm reporting access and no financial write controls.

Record the role, URL, visible action, attempted forbidden action, HTTP result, and screenshot. A read-only POST must be denied before any LedgerOS request or local accounting-state change.

## 8. Maintenance lifecycle

Sign in as `beta-manager` and open the maintenance queue.

1. Open the unit 101 request, “Kitchen sink is leaking into the cabinet.” and confirm Cedar Grove, unit 101, Avery Jordan, Plumbing, Ace Plumbing, urgent priority, and `240.00` estimate.
2. Move it through Triage, Assign, Start, and Verify.
3. Close it with **Vendor invoice pending** and a meaningful closure note.
4. Confirm the event history records each actor, old state, new state, reason, and version.
5. Reopen it with a reason. Confirm the prior close event remains and the reopen count increases.
6. Open the unit 102 request, “Hallway light flickers intermittently.”, resume it, and confirm it returns to its prior Triaged state.

Expected accounting result: none. Maintenance transitions must not create a bill, payment, journal, tenant-ledger line, owner-statement line, sync record, or LedgerOS mutation.

## 9. Maintenance-to-vendor-bill handoff

Sign in as `beta-bookkeeper`. This scenario demonstrates a linking dependency: a bill must belong to the same property and, for a unit-specific maintenance request, the same unit. The existing **GreenLine Landscaping \$315.00 draft bill** starts with no unit selected and the description **Monthly landscaping service**.

1. Open the unit 103 maintenance request, “Remove fallen branches and restore the rear walkway.” Under **Link an existing bill**, notice that the GreenLine bill is absent. It exists, but its unit does not match the request.
2. Open **Vendor Bills**, find the existing GreenLine Landscaping \$315.00 draft, and choose **Edit**.
3. For this demo, treat that draft as the invoice for the walkway repair. Keep **Cedar Grove Apartments**, select unit **103**, change the repair description to **Remove fallen branches and restore the rear walkway.**, and choose **Save draft**. In actual use, only change attribution when it matches the vendor invoice and work performed.
4. Return to the maintenance request. Under **Link an existing bill**, select the GreenLine Landscaping \$315.00 bill and choose **Link bill**. No new bill is needed.
5. Confirm the bill appears once in the linked-bills table and the request remains Closed with Vendor invoice pending.
6. Open the linked bill and confirm it links back to the request. Approval and posting should remain in their draft states; linking does not approve, post, or pay it.

Property managers can link compatible existing bills, but editing this draft requires a bookkeeper or administrator. If the bill already has the matching unit and description from an earlier walkthrough, skip the edit. If it is already linked, review the existing link instead of creating another bill.

Expected accounting result: none until the bill is separately approved and posted. Maintenance closure must remain independent from bill approval, posting, and payment.

## 10. Bill approval, posting, and payment

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

## 11. Advanced: partial deposit and a prepared receipt

This is a separate advanced exercise using Avery’s prefilled records. The first walkthrough used Dana and a full deposit; this one tests partial collection and recovery. If Avery’s records have already been posted or altered, do not assume the amounts below are a fresh starting state. Review their existing activity first.

**Scenario: Avery Jordan pays the rent and part of the required deposit with one check.** The seeded tenant is Avery Jordan, in unit 101.

First establish what Avery owes. Open **Leases**, choose **View** for Avery’s unit 101 lease, and review:

| Obligation | Where it is recorded | Amount |
| --- | --- | --- |
| Monthly rent | Lease rent amount and the current rent invoice | \$1,450.00 |
| Required security deposit | Lease’s deposit required amount | \$1,450.00 |
| **Total owed before payment** | **Rent plus required deposit, assuming neither has been paid** | **\$2,900.00** |

The simulated check pays part of that total:

| Component | Owed before payment | Check applied | Still owed |
| --- | ---: | ---: | ---: |
| Rent | \$1,450.00 | \$1,450.00 | \$0.00 |
| Security deposit | \$1,450.00 | \$500.00 | \$950.00 |
| **Total** | **\$2,900.00** | **\$1,950.00** | **\$950.00** |

The \$1,450.00 invoice covers **rent only**. The deposit requirement was entered on the lease; this scenario does not create a deposit invoice or add the deposit to rent receivables. The later \$500.00 is a **partial payment toward the \$1,450.00 deposit**, not a new charge or the full deposit requirement.

For this exercise, assume no previous deposit money has been received. The seed also includes a separate **draft** \$1,450.00 “Security deposit received for unit 101” event. It is an unposted example, not evidence of payment. Leave it in draft during this scenario; posting it would record additional money outside the check described below.

**The receipt is not a request for payment.** PropertyLedger records money received outside the app; it does not collect the money. The seed has prepared a draft \$1,950.00 receipt to save typing. No real payment occurred. Only continue to allocation and posting after adopting the simulated check-received step below. In actual use, record a receipt after receiving the payment.

**Prerequisite: explicitly provision the tenant customer.** The seed creates Avery Jordan locally but does not provision a LedgerOS customer. A healthy setup smoke check does not confirm that the customer exists.

1. Sign in as `beta-admin` or `beta-manager` and open **Tenants**.
2. Choose **View** for Avery Jordan, then **Provision in LedgerOS**.
3. Review the tenant name, customer code, and default AR account. Choose **Provision in LedgerOS** on the review page to submit the request.
4. Confirm **Tenant customer provisioned in LedgerOS.** This creates a missing customer or verifies an exact match; it does not update a conflicting customer or post an invoice, receipt, or journal. If a conflict is reported, have an administrator review the customer mapping before continuing.

This requires LedgerOS's strict `/api/v1/customers/provision/` endpoint. Deploy the matching LedgerOS change before testing; there is no fallback to customer upsert. No migration is required. An unavailable endpoint, missing permission, or failed provisioning blocks this scenario until resolved.

If posting previously failed with `customer_code: Unknown customer.`, the invoice's sync log provides recovery guidance. Admins and property managers can follow **Review tenant provisioning**; bookkeepers must ask one of those users to perform provisioning. After confirmed provisioning, open the same failed invoice with **View** and choose **Approve and post to LedgerOS** in **LedgerOS Sync**. Provisioning does not retry the invoice, so its historical failure warning remains until a successful retry. The warning describes the last attempt rather than the current LedgerOS customer state; **Review invoice and post** in the list opens that invoice for an explicit retry. Keep the original charge and receipt so their sync identities are preserved. **Save tenant** only saves local edits; neither tenant edits nor charge approval run provisioning.

Sign in as `beta-bookkeeper`.

1. Open Avery Jordan's current `1450.00` base-rent charge with **View**. If it is already **Synced**, continue to step 2. Otherwise, in **LedgerOS Sync**, choose **Approve and post to LedgerOS** and confirm **Invoice posted to LedgerOS.** The Edit screen offers the same action for the saved invoice; save edits first. Confirm a failed attempt shows its error and retains the action for retry, while a successfully posted invoice shows its sync reference and no posting button.
2. **Simulate receiving payment:** Avery hands you a **\$1,950.00 check**, specifying **\$1,450.00 for rent** and **\$500.00 toward the security deposit**. This is the payment event the following receipt records; the app does not initiate it.
3. Open tenant receipts and select Avery Jordan’s prepared **\$1,950.00 draft**. Review the check payment method, payment date, total, and \$500.00 deposit component tied to the unit 101 lease. Before allocation, **Applied to rent / invoices** is `0.00` and **Still to apply to invoices** is `1450.00`; the rent payment has not yet been applied. Reuse this draft rather than entering the same check again.
4. Choose **Apply rent and post to LedgerOS**. This applies and posts the \$1,450.00 rent portion against the open rent invoice; it is not just a preview. Confirm the allocation succeeds and review its posted reference.
5. Choose **Post receipt to LedgerOS** on the same receipt (also available in **Tenant Receipts** once the rent is fully allocated). This posts the \$500.00 deposit component and confirms that both parts of the check have been recorded. If it fails, fix the reported issue and use the same action on this receipt to retry.
6. Confirm the invoice application and deposit journal each have their own successful reference and the parent receipt is Posted.
7. Open **Security Deposits**. Avery’s lease summary should show **Required by lease \$1,450.00**, **Confirmed received \$500.00**, and **Remaining to collect \$950.00**. In **Deposit activity**, the \$500.00 row should say **Posted — confirmed** and link back to this receipt. The separate \$1,450.00 standalone draft remains **Unposted — not counted as received**; do not post it for the same check.
8. On the separate \$1,450.00 standalone draft, attempting **Sync event** must now be rejected: only \$950.00 remains against the lease requirement. Confirm the event stays unposted and creates no new journal. Do not change its amount merely to make the test pass.
9. Return to the receipt and confirm it shows **Posted** with no further posting action. Automated replay coverage verifies that repeating the same request creates no additional payment or journal.

Expected aggregate LedgerOS result:

- Cash increases `1950.00` exactly once.
- Accounts receivable decreases `1450.00`.
- Tenant security deposit liability increases `500.00`.
- Rent and owner reporting include only the confirmed `1450.00` rent component.
- Deposit reporting includes only the confirmed `500.00` liability component.
- Against the lease requirement of \$1,450.00, this \$500.00 payment leaves **\$950.00 of deposit still to collect**, assuming no other confirmed deposit activity. This appears in the Security Deposits lease summary; it is not an additional rent invoice. A collection balance needing reconciliation displays **Needs review** instead.

Do not create a replacement receipt after a timeout. Retry the same receipt so its frozen payloads and idempotency identities are reused.

## 12. Reports and history for the prepared scenarios

After the accounting scenarios succeed:

1. Open Avery Jordan's tenant ledger. Confirm the rent charge and `1450.00` confirmed rent receipt; the `500.00` deposit must not appear as rent.
2. Open the Cedar Grove property and owner reports. Confirm the posted bill expense is present once and partial/full payments do not duplicate it.
3. Open security-deposit reporting and confirm the `500.00` receipt component appears as deposit activity.
4. Open the audit log and verify the maintenance, approval, posting, and payment actors.

Treat an upstream-derived value as **Unavailable** during a read failure. A zero value is not an acceptable substitute.

## 13. LedgerOS outage and recovery

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
