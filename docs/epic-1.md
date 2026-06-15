# Epic 1 Runbook

## Purpose

This document contains everything needed to start up and test Epic 1 for PropertyLedger.

Epic 1 includes:

- Django backend project structure;
- Django REST Framework API layer;
- PostgreSQL-backed local development stack for PropertyLedger;
- real LedgerOS full-stack local setup through a sibling LedgerOS repo;
- environment-based LedgerOS configuration;
- deterministic local health checks;
- deterministic LedgerOS health checks;
- locked `LedgerOSSyncRecord` schema and uniqueness rules;
- basic admin/setup screen for LedgerOS connection settings;
- local-only LedgerOS integration contract.

Epic 1 does not include:

- rent generation;
- tenant charges or payments;
- vendor bills;
- owner statements;
- banking and reconciliation workflows beyond connectivity checks;
- any property-management workflow beyond the foundation and adapter boundary.

## Files To Know

- [`README.md`](/Users/tim/projects/propertyledger/README.md)
- [`Makefile`](/Users/tim/projects/propertyledger/Makefile)
- [`.env.example`](/Users/tim/projects/propertyledger/.env.example)
- [`docker-compose.yml`](/Users/tim/projects/propertyledger/docker-compose.yml)
- [`docker-compose.ledgeros.yml`](/Users/tim/projects/propertyledger/docker-compose.ledgeros.yml)
- [`docs/propertyledger-implementation-epics.md`](/Users/tim/projects/propertyledger/docs/propertyledger-implementation-epics.md)
- [`docs/ledgeros-integration-contract.md`](/Users/tim/projects/propertyledger/docs/ledgeros-integration-contract.md)

## Required Environment Variables

Copy `.env.example` to `.env` and set values for your local environment.

Required:

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
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`

Optional:

- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

Full-stack in-container defaults:

- `DATABASE_HOST=propertyledger-db`
- `LEDGEROS_BASE_URL=http://ledgeros-web:8000`
- `LEDGEROS_HEALTH_PATH=/api/v1/health/`
- `LEDGEROS_TIMEOUT_SECONDS=5`

## Start Up

Use Docker Compose only. The default Epic 1 path starts the real LedgerOS stack.

1. Clone the LedgerOS repo in a sibling directory. The bundled compose file expects it at `../ledgeros_v2`.
2. Clone the PropertyLedger repo.
3. Copy `.env.example` to `.env`.
4. Start the full stack:

```bash
make up
```

5. Run migrations for both repos:

```bash
make migrate
```

6. Run the smoke checks:

```bash
make smoke
```

The local setup screen will be available at:

- `http://localhost:8000/`

## Runtime Endpoints

- `GET /` - setup screen for LedgerOS connection settings
- `GET /api/health/local/` - deterministic local app/database health check
- `GET /api/health/ledgeros/` - deterministic LedgerOS connectivity check
- `POST /api/sync-records/` - create a `LedgerOSSyncRecord`

## Testing

Run the Epic 1 test suite in Docker only.

```bash
make test
```

Run Django checks in Docker only:

```bash
make check
```

## Useful Commands

- `make help` - show available Make targets
- `make up` - start PropertyLedger plus real LedgerOS
- `make down` - stop the stack
- `make migrate` - run migrations for PropertyLedger and LedgerOS
- `make smoke` - verify the full-stack health checks
- `make shell` - open a Django shell inside the PropertyLedger web container

## Health Check Behavior

### Local health check

The local health check is deterministic and verifies only the PropertyLedger app runtime and database reachability.

### LedgerOS health check

The LedgerOS health check is deterministic and returns healthy only when the configured LedgerOS health endpoint returns HTTP 200 with a JSON payload containing `{"status":"ok"}` or `{"status":"healthy"}`.

Missing configuration, timeout, connection error, authentication failure, non-2xx response, malformed response, or unexpected payload is unhealthy.

The full-stack default health path is `/api/v1/health/` to match the current LedgerOS repo.

## Sync Record Contract

`LedgerOSSyncRecord` is locked for Epic 1.

Required fields:

- `local_object_type`
- `local_object_id`
- `ledgeros_resource_type`
- `ledgeros_resource_id`
- `ledgeros_journal_entry_id`
- `source_event_type`
- `external_id`
- `idempotency_key`
- `request_hash`
- `response_payload`
- `status`
- `last_error`
- `attempt_count`
- `last_synced_at`
- `created_at`
- `updated_at`

Allowed statuses:

- `pending`
- `in_progress`
- `succeeded`
- `failed`
- `duplicate`
- `cancelled`

Uniqueness constraints:

- unique `local_object_type`, `local_object_id`, `source_event_type`
- unique `idempotency_key`
- unique `external_id`, `source_event_type`

## Local Contract Reference

The local LedgerOS integration assumptions for Epic 1 are documented in:

- [`docs/ledgeros-integration-contract.md`](/Users/tim/projects/propertyledger/docs/ledgeros-integration-contract.md)

## Suggested First Check

After starting the stack, open the setup screen and confirm:

1. The local health check is healthy.
2. The LedgerOS health check reflects your configured LedgerOS endpoint at `/api/v1/health/`.
3. The LedgerOS connection settings save successfully.
