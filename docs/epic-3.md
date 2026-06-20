# Epic 3 Runbook

## Purpose

This document contains the working guide for Epic 3 in PropertyLedger.

Epic 3 adds the rent-roll and tenant-charge workflow:

- monthly base rent generation from active leases;
- manual one-off tenant charges;
- property-level manual charges that are not tied to a lease;
- charge approval and sync handoff to LedgerOS through the adapter boundary;
- charge visibility in the tenant-ledger workflow.

Epic 3 does not include:

- automated late-fee rules;
- online payments;
- tenant portal features;
- rent escalations;
- non-monthly recurring charges;
- cash-basis reporting;
- vendor bills;
- owner statements;
- banking and reconciliation workflows beyond charge sync handoff.

## Files To Know

- [`README.md`](../README.md)
- [`Makefile`](../Makefile)
- [`.env.example`](../.env.example)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docker-compose.ledgeros.yml`](../docker-compose.ledgeros.yml)
- [`docs/propertyledger-prd.md`](../docs/propertyledger-prd.md)
- [`docs/propertyledger-implementation-epics.md`](../docs/propertyledger-implementation-epics.md)
- [`docs/epic-1.md`](../docs/epic-1.md)
- [`docs/epic-2.md`](../docs/epic-2.md)
- [`docs/epic-1-lessons-learned.md`](../docs/epic-1-lessons-learned.md)
- [`docs/epic-2-lessons-learned.md`](../docs/epic-2-lessons-learned.md)
- [`ledgeros/models.py`](../ledgeros/models.py)
- [`ledgeros/forms.py`](../ledgeros/forms.py)
- [`ledgeros/services.py`](../ledgeros/services.py)
- [`ledgeros/views.py`](../ledgeros/views.py)
- [`ledgeros/urls.py`](../ledgeros/urls.py)
- [`ledgeros/admin.py`](../ledgeros/admin.py)
- [`ledgeros/migrations/0004_tenantcharge.py`](../ledgeros/migrations/0004_tenantcharge.py)
- [`ledgeros/tests/test_models_and_api.py`](../ledgeros/tests/test_models_and_api.py)

## Required Environment Variables

Copy `.env.example` to `.env` for local and Docker Compose work.

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

Use the same LedgerOS client values you already use for Epic 1 and Epic 2.

## Start Up

Use Docker Compose only.

1. Clone the LedgerOS repo in a sibling directory if you want the full-stack path. The bundled compose file expects it at `../ledgeros_v2`.
2. Clone the PropertyLedger repo.
3. Copy `.env.example` to `.env` if you want to override the defaults.
4. Start the stack:

```bash
make up
```

5. Run migrations:

```bash
make migrate
```

6. Run the smoke checks:

```bash
make smoke
```

The app UI will be available at:

- `http://localhost:8000/`

## Admin Access

Create a superuser in each repo before using the admin screens:

- PropertyLedger:

```bash
docker compose -f docker-compose.yml -f docker-compose.ledgeros.yml exec propertyledger-web python manage.py createsuperuser
```

- LedgerOS:

```bash
cd ../ledgeros_v2
docker compose exec web python manage.py createsuperuser
```

Admin URLs:

- PropertyLedger admin: `http://localhost:8000/admin/`
- LedgerOS admin: `http://localhost:8001/admin/`

## Runtime Endpoints

- `GET /charges/` - tenant charges list
- `GET /charges/add/` - create tenant charge
- `GET /charges/<id>/edit/` - edit tenant charge
- `POST /charges/<id>/archive/` - archive tenant charge

## Domain Rules

### Charge types

Allowed charge types:

- `base_rent`
- `utility_reimbursement`
- `late_fee_manual`
- `other_manual`

### Charge scope

- Lease-based base rent is inferred from the lease.
- Manual charges may be attached to a lease, but they do not have to be.
- Property-level manual charges must still belong to a property.
- Base rent cannot be created without a lease.

### Rent generation

- Base rent is generated monthly from active leases.
- Base rent for a lease that starts or ends mid-month is prorated.
- A generated base rent charge is unique by lease and billing period.
- Re-running rent generation for the same lease/month must not create a duplicate charge.

### Charge editing

- Draft charges may be edited normally.
- Approving a charge starts the sync handoff immediately.
- After sync, only `due_date` and `description` remain editable.

### Sync behavior

- Approval creates or updates a `LedgerOSSyncRecord`.
- The repo treats the sync record as the accounting handoff boundary.
- Do not bypass the service layer when changing charge status or sync behavior.

## Testing

Run tests in Docker only.

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test ledgeros.tests.test_models_and_api
```

Run Django checks in Docker:

```bash
make check
```

## Manual Checks

- Create a lease with a mid-month start date and verify the generated base rent is prorated.
- Re-run rent generation for the same lease/month and verify no duplicate charge appears.
- Create a property-level manual charge without a lease and verify it saves.
- Approve a charge and verify the sync record is created or updated.
- Confirm a synced charge cannot be edited beyond `due_date` and `description`.

## Useful Commands

- `make help` - show available Make targets
- `make up` - start PropertyLedger plus real LedgerOS
- `make down` - stop the stack
- `make reset` - stop the stack and remove volumes
- `make migrate` - run migrations for PropertyLedger and LedgerOS, then bootstrap saved connection settings, setup prerequisite rows, and demo account mappings
- `make smoke` - verify the full-stack health checks
- `make shell` - open a Django shell inside the PropertyLedger web container

## Notes

This runbook should stay aligned with the Epic 3 implementation section in `docs/propertyledger-implementation-epics.md`. If the code and docs drift, update both together.
