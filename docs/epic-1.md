# Epic 1 Runbook

## Purpose

This document contains everything needed to start up and test Epic 1 for PropertyLedger.

Epic 1 includes:

- Django backend project structure;
- Django REST Framework API layer;
- PostgreSQL-backed local development stack for PropertyLedger;
- real LedgerOS connectivity through a separate running LedgerOS endpoint;
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

- [`README.md`](../README.md)
- [`Makefile`](../Makefile)
- [`.env.example`](../.env.example)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docker-compose.ledgeros.yml`](../docker-compose.ledgeros.yml)
- [`docs/propertyledger-implementation-epics.md`](./propertyledger-implementation-epics.md)
- [`docs/ledgeros-integration-contract.md`](./ledgeros-integration-contract.md)
- [`docs/epic-1-lessons-learned.md`](./epic-1-lessons-learned.md)

## Required Environment Variables

Copy `.env.example` to `.env`. Leave the LedgerOS values blank for PropertyLedger-only local work, or fill them in using the LedgerOS values from your running LedgerOS environment.

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
- `LEDGEROS_HOST_HEADER`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

PropertyLedger-only defaults with LedgerOS endpoint values:

- `DATABASE_HOST=propertyledger-db`
- `LEDGEROS_BASE_URL=http://host.docker.internal:8001`
- `LEDGEROS_HOST_HEADER=localhost:8001`
- `LEDGEROS_HEALTH_PATH=/api/v1/health/`
- `LEDGEROS_TIMEOUT_SECONDS=5`
- `LEDGEROS_CLIENT_ID=api_full` if that is the client configured in LedgerOS
- `LEDGEROS_HMAC_SECRET` should match the LedgerOS secret for that client and must come from the LedgerOS side
- `LEDGEROS_API_KEY=` unless the sibling LedgerOS repo requires bearer auth

Copy-paste starter values:

```dotenv
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
DATABASE_ENGINE=django.db.backends.postgresql
DATABASE_NAME=propertyledger
DATABASE_USER=propertyledger
DATABASE_PASSWORD=propertyledger
DATABASE_HOST=propertyledger-db
DATABASE_PORT=5432
LEDGEROS_BASE_URL=http://host.docker.internal:8001
LEDGEROS_HOST_HEADER=localhost:8001
LEDGEROS_CLIENT_ID=api_full
LEDGEROS_HMAC_SECRET=change-me
LEDGEROS_API_KEY=
LEDGEROS_HEALTH_PATH=/api/v1/health/
LEDGEROS_TIMEOUT_SECONDS=5
```

If the sibling LedgerOS repo uses different API client values, change only `LEDGEROS_CLIENT_ID`, `LEDGEROS_HMAC_SECRET`, and `LEDGEROS_API_KEY` if needed.

## Start Up

Use Docker Compose only. The default Epic 1 path starts PropertyLedger only and points to an already running LedgerOS endpoint.

1. Clone the PropertyLedger repo.
2. If you want to customize the environment, copy `.env.example` to `.env` and set the LedgerOS connection values there.
3. Start the PropertyLedger stack:

```bash
make up
```

4. Run migrations:

```bash
make migrate
```

5. Run the smoke checks:

```bash
make smoke
```

## Testing

All Epic 1 tests run in Docker. Use compose-based commands rather than host Python:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test
make check
```

The local setup screen will be available at:

- `http://localhost:8000/`

## Admin Access

Create a superuser in PropertyLedger before using the admin screens:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py createsuperuser
```

Admin URLs:

- PropertyLedger admin: `http://localhost:8000/admin/`
- LedgerOS admin is managed separately in the LedgerOS repo or deployment.

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
- `make up` - start PropertyLedger only
- `make down` - stop the stack
- `make reset` - stop the stack and remove volumes
- `make migrate` - run PropertyLedger migrations, then bootstrap saved connection settings and setup prerequisite rows
- `make smoke` - verify the configured LedgerOS health check and the PropertyLedger runtime
- `make shell` - open a Django shell inside the PropertyLedger web container

## Health Check Behavior

### Local health check

The local health check is deterministic and verifies only the PropertyLedger app runtime and database reachability.

### LedgerOS health check

The LedgerOS health check is deterministic and returns healthy only when the configured LedgerOS health endpoint returns HTTP 200 with a JSON payload containing `{"status":"ok"}` or `{"status":"healthy"}`.

Missing configuration, timeout, connection error, authentication failure, non-2xx response, malformed response, or unexpected payload is unhealthy.

The default LedgerOS health path is `/api/v1/health/` to match the current LedgerOS repo.

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

- [`docs/ledgeros-integration-contract.md`](../docs/ledgeros-integration-contract.md)

## Suggested First Check

After starting the stack, open the setup screen and confirm:

1. The local health check is healthy.
2. The LedgerOS health check reflects your configured LedgerOS endpoint at `/api/v1/health/`.
3. The LedgerOS connection settings save successfully.
