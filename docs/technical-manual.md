# PropertyLedger Technical Manual

## Purpose

This manual is for developers, maintainers, and connector authors who need to understand how PropertyLedger is built, how it talks to LedgerOS, and how the accounting boundaries are enforced.

## What PropertyLedger is

PropertyLedger is a real estate accounting client for LedgerOS.

It owns the property-management domain:

- properties;
- units;
- owners;
- tenants;
- leases;
- rent roll;
- maintenance expense context;
- owner statements;
- local workflow status;
- sync mappings to LedgerOS.

LedgerOS remains the accounting system of record for:

- chart of accounts;
- accounting periods;
- invoices;
- bills;
- payments;
- journal entries;
- banking and reconciliation records;
- reports;
- audit trail;
- accounting invariants.

## Architecture

```text
PropertyLedger domain
  -> accounting adapter interface
  -> LedgerOS adapter implementation
  -> LedgerOS HTTP API/services
```

PropertyLedger must not:

- import LedgerOS Django models into domain code;
- write directly to the LedgerOS database;
- bypass LedgerOS APIs/services for accounting mutations;
- treat local unsynced data as posted accounting facts.

## Public programmatic surface

The current public `/api` surface is intentionally narrow:

- `GET /api/health/local/`
- `GET /api/health/ledgeros/`
- `POST /api/v1/sync-events/`

UI routes under `/`, `/owners/`, `/properties/`, `/charges/`, and `/payments/` are application pages, not stable external API.

## Sync and idempotency

PropertyLedger uses sync records to track LedgerOS-bound events.

Key rules:

- state-changing accounting actions go through the adapter boundary;
- each logical outbound event uses a stable external ID;
- retries must reuse the same idempotency key;
- duplicate detection is explicit;
- a sync record does not by itself prove LedgerOS posting succeeded unless the flow explicitly says so;
- request/response payloads should be logged with secret redaction.

## Main workflows

### Setup and onboarding

- Configure LedgerOS connection settings.
- Run deterministic local and LedgerOS health checks.
- Select the LedgerOS entity and accounting period.
- Configure required account mappings.
- Run a smoke test.

### Property data

- Create and archive owners, properties, units, tenants, and leases.
- Respect dependency order when creating records.

### Tenant charges

- Generate recurring base rent from active leases.
- Create manual tenant charges.
- Approve/sync charges through the service layer.

### Payments and deposits

- Record tenant payments.
- Apply payments to invoices.
- Track security deposit events and balances.

Tenant charges create invoices through `POST /api/v1/invoices/`. Allocating a
tenant payment posts one payment per invoice allocation through LedgerOS
`POST /api/v1/payments/`, with `source_type = "invoice"`, the invoice's stable
external reference, payment date, and allocated amount. LedgerOS debits Cash,
credits AR, and reduces the invoice balance. A receipt split across invoices
therefore maps to several LedgerOS payment and journal IDs.

An allocation succeeds only when LedgerOS returns a payment ID and a journal ID
with journal status `posted`. Retrying preserves the allocation, request body,
and idempotency key; confirmed allocations are skipped. Accounting fields are
locked after an allocation has been attempted, including timeout cases where
LedgerOS might already have committed the payment. Notes remain editable.

Finalizing the receipt retries unconfirmed allocations and requires the entire
receipt amount to be allocated and posted. It sends no parent receipt event to
LedgerOS and never posts the money again. The parent's `LedgerOSSyncRecord` is
a local `payment_collection` summary under `tenant_payment.finalized`; its
response lists the allocation sync records, LedgerOS payment IDs, journal IDs,
and amounts. Existing report queries continue to use the parent's succeeded
sync status. Failed finalization remains outside official receipt totals.
Unapplied amounts are local operational data, not posted tenant credit.

Legacy `tenant_payment.received` sync-event rows are retained unchanged. When a
receipt is finalized again, its parent link moves to the new local summary;
the original row remains available by local object identity in sync history.
Existing allocation records are reused. A changed retry payload is rejected
for manual reconciliation rather than sent with a new idempotency key. No data
migration or automatic reposting is performed.

Security-deposit events retain their existing generic sync-event contract.

For manual acceptance in a prepared Docker sandbox, create two posted invoices
for the same tenant/property for `40.00` and `60.00`, then allocate a `100.00`
receipt. Confirm two LedgerOS payments and posted Cash/AR journals, invoice
balances of zero, and a total receipt of `100.00` on the tenant ledger after
finalization. Finalize again and confirm no extra payment or journal. For a
`60.00` receipt against a `100.00` invoice, expect a remaining invoice balance of
`40.00`. Test a failed allocation by interrupting LedgerOS availability, then
restore it and retry the same receipt; payment IDs for successful allocations
must remain unchanged. No reset of an existing bookkeeping database is needed.

### Vendor and debt workflows

- Record vendors, bills, vendor payments, and debt-service payments.
- Keep credit-card and liability workflows behind the supported adapter paths.

Bill payment status is read from LedgerOS using authenticated
`GET /api/v1/bills/` batches of up to 100 repeated `external_bill_number`
parameters. Only the integration client's own bill references are returned.
The bill list and detail page share this read path. The list's GET
`payment_status` filter selects unpaid, partially paid, paid, not posted,
voided, needs review, or unavailable bills. The maintenance expense summary
continues to cover all bills and is labeled accordingly.

Balances are current subledger balances, not period report totals. Amount paid
and credits applied are separate; balance due equals bill amount minus both.
Payments and credits entered directly in LedgerOS are included when applied to
the bill. Failed/local-only payments and credit-card payoffs do not settle a
bill. Unallocated general journal adjustments remain outside individual bill
balances. No bill posting, payment posting, or reconciliation runs during GET.
Missing, unreachable, or invalid upstream data displays Unavailable. Inconsistent
totals and linked reversed journals require review rather than showing Paid.
Historical applications without a journal link retain their existing LedgerOS
subledger meaning; reversal detection for those records remains limited.

New credit-card bill payments use `POST /api/v1/payments/` with
`source_type=bill`, the bill's external reference, and the configured
`funding_account_code`. LedgerOS posts debit AP / credit card liability and
creates a bill payment application. The local event is
`vendor_payment.credit_card_settled`; standard vendor payment identity is
unchanged. Credit-card payoff remains a separate generic journal event that
reduces card liability and Cash, and does not settle the bill again.

Legacy card payments used generic journal events without bill applications.
They display Needs review until explicitly reconciled. Retrying an existing
legacy card payment sends its `existing_sync_event_id` with the payment request.
LedgerOS validates client ownership, the exact AP/funding accounts and amount,
and the original posted, unreversed journal. It attaches that journal once
without posting again or changing its date. The original local sync event is
retained; a separate settlement record stores the resulting payment ID.
Retries reuse that settlement's identity and payload, and attempted payments'
accounting fields are locked. Missing or ambiguous historical journal evidence
requires manual reconciliation; it never triggers a replacement posting.

Deploy the updated LedgerOS code and migration 0011 before this client change.
The client needs `bills` scope for reads and the existing `payments` scope and
`payment.post_requested` permission for settlements. In a local sibling setup:

```bash
docker compose -f ../ledgeros_v2/docker-compose.yml run --rm web python manage.py migrate
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py reconcile_bill_card_payments
# After reviewing the preview, reconcile one existing payment:
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py reconcile_bill_card_payments --apply --payment-id 123
```

The preview is read-only. Apply creates missing payment/application records
against verified existing journals; journal count and account balances must
stay unchanged. Never reset bookkeeping data to perform this upgrade.

| Requirement | Source | Implementation | Verification |
| --- | --- | --- | --- |
| Bill status and filtering | Issue 20 | `BillPaymentStatusService`, bill views/templates | `test_bill_payment_status` list/detail/filter tests |
| Payments and credits outside PropertyLedger | Issue 20 | LedgerOS scoped bill read API | LedgerOS API payment/credit balance tests |
| Card settlement without double counting | Issue 20 | Payment adapter, LedgerOS application link | Card GL, payoff exclusion, and retry tests |
| Historical card journals | Approved recommendation | Reconciliation command and existing-journal API | Preview/apply and duplicate/mismatch tests |
| Unallocated journal attribution | Explicitly deferred | Requires an allocation workflow | No inferred bill adjustments |

For manual acceptance in a Docker sandbox, post a 100.00 bill, apply a 40.00
payment and 10.00 vendor credit in LedgerOS, and confirm Partially paid with
50.00 due in PropertyLedger. Check each status filter and the matching detail
page. Settle the remainder and confirm Paid. A card payment must debit AP and
credit card liability; paying off the card must not reduce the bill again.
For a legacy card journal, preview and apply the reconciliation command, then
repeat it: journal count and GL balances must remain unchanged. Disconnecting
LedgerOS should show Unavailable, and viewing a draft should make no API call.

### Paying a bill from its detail page (Issue 23)

The internal UI route `/payments/vendor-bills/<id>/pay/` uses the existing vendor
payment form and service path, scoped to the bill and its vendor on the server.
GET reads the current LedgerOS balance and prepares a review form; it creates
no payment or posting. New POST submissions require a locally posted,
successfully synced bill and a confirmed unpaid/partially-paid balance. Payment
amount must be positive and no greater than that balance. LedgerOS's locked
bill-balance validation remains authoritative if another payment races with the
form submission. Credit-card payoff is excluded from this workflow.

Each form has a signed token binding a random submission UUID to its bill and
user, valid for 24 hours. `VendorPayment.submission_id` is nullable and unique;
`submission_hash` records a fingerprint of the normalized reviewed fields.
Migration `payments.0005_vendorpayment_submission` adds these fields without
altering existing payments. Apply it with the normal Docker migration command.
The local payment identity is persisted before the external write. Duplicate
submissions reuse it; changed details under the same UUID are rejected. Sync
locks the payment row and reads related state after acquiring the lock, so
concurrent submissions reuse one LedgerOS result and idempotency key.

Retries of an existing submission do not require a positive fresh balance:
LedgerOS may already have posted it before a timeout. The original payload and
idempotency key are reused. The bill shows pending payments, recorded errors,
and an explicit retry action. Bookkeeper/admin authorization is enforced on
both the new payment route and the existing payment-detail retry POST. Signed
tokens do not replace CSRF or role checks. An expired form can be recovered by
retrying the saved payment from the bill rather than creating another payment.

For a 100.00 bill and a 40.00 bank payment, expect
`POST /api/v1/payments/` with `source_type=bill`, the bill's stable external
reference, date, and amount 40.00. LedgerOS posts debit AP / credit Cash and
leaves 60.00 due. Card payments instead credit the configured card liability.
Repeating the form creates neither another local payment nor another journal.
Accrual expense and owner-statement bill totals remain 100.00; tenant ledgers
and unrelated property/owner attribution do not change. No LedgerOS API changes
are required by Issue 23.

| Requirement | Implementation | Automated check |
| --- | --- | --- |
| Pay from a synced bill, partial/full payments and card funding | `VendorBillPayView`, `BillPaymentForm`, `VendorPaymentService.pay_bill` | `test_bill_payment_flow` |
| Duplicate, concurrent and timeout recovery | Submission UUID/fingerprint and payment-row lock | Duplicate, timeout and concurrency tests |
| Eligibility, fixed bill/vendor, role and token checks | Bill-scoped form/view and service validation | Blocked-state, stale balance, tampering and read-only tests |

For Docker manual acceptance, migrate first, open a posted 100.00 sandbox bill,
and select Pay bill. Confirm that opening the form creates no payment. Post
40.00 and verify 60.00 due and one LedgerOS journal. Resubmit the same form and
confirm the payment/journal count is unchanged. Use the remaining 60.00 to
settle the bill, then confirm no new Pay bill action. Test a failed post and
retry the saved payment from the bill. A read-only user must be denied both
payment submission and retry. Automated verification is:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test payments.tests.test_bill_payment_flow
```

### Reports and statements

- Use synced records for operational and accounting reports.
- Keep draft/unsynced data out of official totals.

### Banking visibility

- Read bank account summaries and reconciliation summaries from LedgerOS.
- Keep the banking view read-only in MVP.

## Configuration

Use environment variables for local and deployed configuration.

Important values:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_ENGINE`
- `DATABASE_NAME`
- `DATABASE_USER`
- `DATABASE_PASSWORD`
- `DATABASE_HOST`
- `DATABASE_PORT`
- `LEDGEROS_BASE_URL`
- `LEDGEROS_HOST_HEADER`
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

## Testing and verification

Run automated checks in Docker.

Typical commands:

```bash
make up
make migrate
make smoke
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test
make check
```

Do not rely on host Python or host-installed Django dependencies.

## See also

- [Quick Start Guide](./quick-start.md)
- [User Manual](./user-manual.md)

