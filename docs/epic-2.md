# Epic 2 Runbook

## Purpose

This document contains everything needed to work on, start, and verify Epic 2 for PropertyLedger.

Epic 2 includes:

- the full MVP setup/onboarding foundation;
- property CRUD;
- unit CRUD;
- owner CRUD;
- tenant CRUD;
- lease CRUD;
- setup status persistence;
- setup status visibility in the UI;
- required LedgerOS account mapping validation;
- one-primary-owner-per-property workflow.

Epic 2 does not include:

- rent generation;
- tenant charges or payments;
- vendor bills;
- owner statements;
- banking and reconciliation workflows beyond setup and connectivity;
- fractional ownership;
- multi-owner allocation;
- tenant portal;
- bank feeds.
- bulk load/import flows for tenants and units.

## Files To Know

- [`README.md`](../README.md)
- [`Makefile`](../Makefile)
- [`.env.example`](../.env.example)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docker-compose.ledgeros.yml`](../docker-compose.ledgeros.yml)
- [`docs/propertyledger-prd.md`](../docs/propertyledger-prd.md)
- [`docs/propertyledger-implementation-epics.md`](../docs/propertyledger-implementation-epics.md)
- [`docs/epic-1.md`](../docs/epic-1.md)
- [`docs/epic-1-lessons-learned.md`](../docs/epic-1-lessons-learned.md)
- [`docs/epic-2-lessons-learned.md`](../docs/epic-2-lessons-learned.md)
- [`ledgeros/models.py`](../ledgeros/models.py)
- [`ledgeros/forms.py`](../ledgeros/forms.py)
- [`ledgeros/views.py`](../ledgeros/views.py)
- [`ledgeros/urls.py`](../ledgeros/urls.py)
- [`ledgeros/templates/ledgeros/base.html`](../ledgeros/templates/ledgeros/base.html)
- [`ledgeros/templates/ledgeros/setup.html`](../ledgeros/templates/ledgeros/setup.html)
- [`ledgeros/templates/ledgeros/crud_list.html`](../ledgeros/templates/ledgeros/crud_list.html)
- [`ledgeros/templates/ledgeros/crud_form.html`](../ledgeros/templates/ledgeros/crud_form.html)
- [`ledgeros/templates/ledgeros/crud_confirm_delete.html`](../ledgeros/templates/ledgeros/crud_confirm_delete.html)

## Required Environment Variables

Copy `.env.example` to `.env` and set the LedgerOS connection values from your running LedgerOS environment.

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

PropertyLedger-only defaults with LedgerOS endpoint values:

- `DATABASE_HOST=propertyledger-db`
- `LEDGEROS_BASE_URL=http://localhost:8001`
- `LEDGEROS_HEALTH_PATH=/api/v1/health/`
- `LEDGEROS_TIMEOUT_SECONDS=5`

If the sibling LedgerOS repo uses a different client configuration, update the LedgerOS client values in `.env`.

## Start Up

Use Docker Compose only. The default Epic 2 path starts PropertyLedger only and uses a separate running LedgerOS endpoint.

1. Clone the PropertyLedger repo.
2. Copy `.env.example` to `.env` if you want a local file to edit.
3. Set the LedgerOS connection values in `.env` or export them in your shell.
4. Run the stack:

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

The main app UI will be available at:

- `http://localhost:8000/`

## Admin Access

Create a superuser in PropertyLedger before using the admin screens:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py createsuperuser
```

Admin URLs:

- PropertyLedger admin: `http://localhost:8000/admin/`
- LedgerOS admin is managed separately in the LedgerOS repo or deployment.

App URLs:

- Setup: `http://localhost:8000/`
- Owners: `http://localhost:8000/owners/`
- Properties: `http://localhost:8000/properties/`
- Units: `http://localhost:8000/units/`
- Tenants: `http://localhost:8000/tenants/`
- Leases: `http://localhost:8000/leases/`

## Runtime Endpoints

- `GET /` - setup screen with LedgerOS connection and setup status
- `GET /properties/` - properties list
- `GET /properties/add/` - create property
- `GET /properties/<id>/edit/` - edit property
- `POST /properties/<id>/archive/` - archive property
- `GET /units/` - units list
- `GET /units/add/` - create unit
- `GET /units/<id>/edit/` - edit unit
- `POST /units/<id>/archive/` - archive unit
- `GET /owners/` - owners list
- `GET /owners/add/` - create owner
- `GET /owners/<id>/edit/` - edit owner
- `POST /owners/<id>/archive/` - archive owner
- `GET /tenants/` - tenants list
- `GET /tenants/add/` - create tenant
- `GET /tenants/<id>/edit/` - edit tenant
- `POST /tenants/<id>/archive/` - archive tenant
- `GET /leases/` - leases list
- `GET /leases/add/` - create lease
- `GET /leases/<id>/edit/` - edit lease
- `POST /leases/<id>/archive/` - archive lease
- `GET /api/health/local/` - deterministic local app/database health check
- `GET /api/health/ledgeros/` - deterministic LedgerOS connectivity check
- `POST /api/sync-records/` - create a `LedgerOSSyncRecord`

## Testing

Run tests in Docker only. Do not rely on host Python or host-installed Django packages.

Run the Epic 2 test slice in Docker:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test ledgeros.tests.test_models_and_api ledgeros.tests.test_health ledgeros.tests.test_management_commands
```

Run Django checks in Docker:

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

## Setup Rules

Setup completion depends on:

1. LedgerOS health succeeding.
2. A LedgerOS entity being selected.
3. An open accounting period being selected.
4. Required account mappings being present and valid.
5. Required bank/card mappings being present and valid.
6. Setup smoke validation passing.

Setup status is stored on `PropertyLedgerSetup.setup_status`. Sync status remains stored on `LedgerOSSyncRecord.status`.

## Domain Rules

### Suggested configuration order

When setting up the app without a wizard, use this order:

1. Setup and LedgerOS connection.
2. Owners.
3. Properties.
4. Units.
5. Tenants.
6. Leases.

That order matches the data dependencies in the forms:

- `Property.primary_owner` requires an owner.
- `Unit.property` requires a property.
- `Lease.unit` requires a unit.
- `Lease.tenant` requires a tenant.

The app surfaces that order in the setup screen and blocks create actions that would violate it.

## Follow-on Feature

The next small follow-on feature after Epic 2 should add bulk load/import support for tenants and units so repetitive master-data entry does not have to happen one record at a time.

### Properties, owners, and units

- Each property has one primary owner.
- Fractional ownership is deferred.
- Properties and units can be archived without deleting historical records.

### Tenants and leases

- Leases require a unit, tenant, start date, and monthly base rent.
- `base_monthly_rent` is a decimal amount.
- `deposit_required` is a decimal amount.
- Rent effective date defaults to lease start date.
- Lease cadence is monthly only.

### Account mappings

Required setup mappings:

- `operating_bank_account`
- `undeposited_funds`
- `accounts_receivable`
- `accounts_payable`
- `rental_income`
- `repairs_and_maintenance_expense`
- `tenant_security_deposits_liability`
- `owner_contributions_equity`
- `owner_distributions_equity`

Required if enabled:

- `credit_card_liability`
- `mortgage_or_loan_liability`
- `interest_expense`
- `principal_payment_mapping`

Example mapping:

| Mapping key | LedgerOS account id | LedgerOS account name | LedgerOS account type |
| --- | --- | --- | --- |
| `rental_income` | `4000` | `Rental Income` | `revenue` |

## Suggested First Check

After starting the stack, open the app and confirm:

1. The local health check is healthy.
2. The LedgerOS health check reflects the configured endpoint at `/api/v1/health/`.
3. The setup page shows setup status and account mapping status.
4. The property, unit, owner, tenant, and lease pages load.
5. You can create and archive a property without deleting its history.
