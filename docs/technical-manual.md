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

