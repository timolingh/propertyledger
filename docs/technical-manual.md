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

