# LedgerOS Integration Contract

## Status

This is a local Epic 1 contract for PropertyLedger implementation planning.
It is not an authoritative LedgerOS specification.

## Purpose

Define the minimum LedgerOS assumptions PropertyLedger needs for Epic 1:

- connection configuration;
- deterministic health checks;
- request signing;
- idempotency;
- sync record persistence;
- safe local development.

## Local assumptions

PropertyLedger talks to LedgerOS through HTTP APIs only.

PropertyLedger does not:

- import LedgerOS Django models;
- write to the LedgerOS database;
- bypass LedgerOS services for accounting mutations;
- treat unsynced local records as posted accounting facts.

## Configuration

PropertyLedger reads LedgerOS integration settings from environment variables.

Required variables:

- `LEDGEROS_BASE_URL`
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`

Optional variables:

- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

Secrets must remain out of the database and out of logs.

## Deterministic health checks

### Local health check

The local health check is deterministic and verifies only the PropertyLedger app runtime and database reachability.

### LedgerOS health check

The LedgerOS health check is deterministic and:

- calls the configured LedgerOS health endpoint;
- defaults to `/api/v1/health/` for the real LedgerOS setup;
- uses the configured timeout;
- returns healthy only when the response is HTTP 200 with JSON payload `{"status":"ok"}` or `{"status":"healthy"}`;
- reports any missing config, timeout, authentication failure, connection error, non-2xx response, or malformed payload as unhealthy.

## Signing and idempotency

PropertyLedger signs LedgerOS-bound requests with the configured HMAC secret.

Idempotency keys must be deterministic for the same logical outbound event.

Idempotency keys must be stable across retries and must be stored with the sync record.

## Invoice submission contract

PropertyLedger submits tenant-charge invoices to:

- `POST /api/v1/invoices/`

The request body must include:

- `customer_code`
- `external_invoice_number`
- `invoice_date`
- `due_date`
- `total_amount`
- `lines`

Each invoice line must include:

- `account_code`
- `line_description`
- `amount`

Write requests must include the HMAC headers used by the LedgerOS API client flow:

- `X-LedgerOS-Client-Id`
- `X-LedgerOS-Timestamp`
- `X-LedgerOS-Nonce`
- `X-LedgerOS-Signature`
- `Idempotency-Key`
- `Content-Type: application/json`

PropertyLedger provisions LedgerOS customers before creating properties and tenants. The invoice customer code is derived from the local object identity, not from the display name:

- properties use `property-{property.pk}`
- tenants use `tenant-{tenant.pk}`

Tenant-charge invoice sync must reuse the same stable customer code rules so retry behavior stays deterministic.

## Sync mapping expectations

Every outbound LedgerOS-bound accounting event must persist a local sync record.

At minimum, the sync record must include:

- local object identity;
- source event type;
- external ID;
- idempotency key;
- request hash;
- response payload;
- sync status;
- timestamps;
- linked LedgerOS resource identifiers when available.

The Epic 1 `LedgerOSSyncRecord` schema and uniqueness constraints are locked in `docs/propertyledger-implementation-epics.md`.

## Implementation boundary for Epic 1

This contract is limited to:

- adapter shape;
- health checks;
- signing;
- idempotency;
- sync records;
- local development assumptions.

It does not define rent generation, billing, payments, reconciliation workflows, owner statements, or other post-Epic 1 features.
