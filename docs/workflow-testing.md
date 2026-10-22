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

## Fixture map

Use `Cedar Grove Apartments`, owned by `Cedar Grove Holdings LLC`.

| Scenario | Seeded record | Initial state |
| --- | --- | --- |
| Rent and deposit | `BETA-MIXED-RECEIPT` for Avery Jordan, unit 101 | Draft receipt for `1950.00`: rent `1450.00`, deposit `500.00`; no allocations posted |
| Maintenance lifecycle | `BETA-MAINT-OPEN` | Urgent leaking sink request, Open |
| Hold and resume | `BETA-MAINT-HOLD` | Hallway light request, On hold while awaiting access |
| Maintenance-to-AP | `BETA-MAINT-INVOICE-PENDING` | Closed and verified; vendor invoice pending; no linked bill |
| Approved payable | Ace Plumbing bill for `240.00` | Approved locally; LedgerOS posting remains separate |
| Approval queue | Bright Electric bill for `180.00` | Submitted by the bookkeeper; awaiting independent approval |
| Draft payable | GreenLine Landscaping bill for `315.00` | Draft |

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

1. Open `BETA-MAINT-OPEN` and confirm Cedar Grove, unit 101, Avery Jordan, Plumbing, Ace Plumbing, urgent priority, and `240.00` estimate.
2. Move it through Triage, Assign, Start, and Verify.
3. Close it with **Vendor invoice pending** and a meaningful closure note.
4. Confirm the event history records each actor, old state, new state, reason, and version.
5. Reopen it with a reason. Confirm the prior close event remains and the reopen count increases.
6. Open `BETA-MAINT-HOLD`, resume it, and confirm it returns to its prior Triaged state.

Expected accounting result: none. Maintenance transitions must not create a bill, payment, journal, tenant-ledger line, owner-statement line, sync record, or LedgerOS mutation.

## 3. Maintenance-to-vendor-bill handoff

Sign in as `beta-bookkeeper` and open `BETA-MAINT-INVOICE-PENDING`. Property managers may link existing bills, while bill creation is reserved for admins and bookkeepers.

1. Start the **Create vendor bill** handoff.
2. Confirm property and request context are prefilled; choose GreenLine Landscaping and enter `315.00` if needed.
3. Save the bill as a draft.
4. Confirm the request remains Closed with Vendor invoice pending.
5. Confirm both request and bill link to each other.
6. Start the handoff again and confirm repeat submission does not create a duplicate bill.

Expected accounting result: none until the bill is separately approved and posted. Maintenance closure must remain independent from bill approval, posting, and payment.

## 4. Bill approval, posting, and payment

1. Sign in as `beta-manager` and open the approval queue.
2. Approve the submitted Bright Electric `180.00` bill. Confirm the original bookkeeper submitter cannot approve it.
3. Sign in as `beta-bookkeeper`. Open the approved Ace Plumbing `240.00` bill.
4. Post the bill to LedgerOS and confirm the local state shows a successful bill resource/reference.
5. Start payment from that bill, record a partial payment of `100.00`, and confirm the remaining payable is `140.00`.
6. Submit the same payment again only as a replay check. Confirm one local payment and one LedgerOS accounting effect.
7. Record the remaining `140.00`. Confirm the bill is fully paid and a new payment action is no longer offered.

Expected accounting behavior: approval itself creates no ledger entry. Bill posting records the expense/payable once. Payments reduce the payable without changing the original expense, owner expense total, or tenant ledger. Every retry retains the same local payment and idempotency identity.

## 5. Combined rent and security-deposit receipt

Sign in as `beta-bookkeeper`.

1. Open Avery Jordan's current `1450.00` base-rent charge and approve/post it to LedgerOS.
2. Open tenant receipts and select `BETA-MIXED-RECEIPT`.
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
