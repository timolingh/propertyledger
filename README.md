# PropertyLedger

**PropertyLedger** is a real estate accounting client for LedgerOS.

It is intended to be built as a separate application from LedgerOS. PropertyLedger owns property-management context such as properties, units, tenants, leases, owners, rent roll, maintenance categories, and owner statements. LedgerOS remains the accounting system of record for invoices, bills, payments, journals, banking, reconciliation, reports, and audit history.

## Current package status

This repository now includes the Epic 1 Django foundation for PropertyLedger:

- Django + Django REST Framework backend;
- PostgreSQL-backed Docker Compose full-stack local setup;
- LedgerOS adapter boundary with real LedgerOS as the only integration target;
- deterministic local and LedgerOS health checks;
- locked `LedgerOSSyncRecord` schema and uniqueness constraints;
- admin/setup screen plus Epic 2 CRUD pages for properties, units, owners, tenants, and leases.

## Environment variables

Use [`.env.fullstack.example`](/Users/tim/projects/propertyledger/.env.fullstack.example) for the primary PropertyLedger plus real LedgerOS Docker Compose setup. Use [`.env.example`](/Users/tim/projects/propertyledger/.env.example) for PropertyLedger-only local work.

Warning: in full-stack Docker mode, `LEDGEROS_BASE_URL` must be `http://ledgeros-web:8000`, not `localhost`.

Quick full-stack starter values:

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
LEDGEROS_BASE_URL=http://ledgeros-web:8000
LEDGEROS_CLIENT_ID=propertyledger
LEDGEROS_HMAC_SECRET=change-me
LEDGEROS_API_KEY=
LEDGEROS_HEALTH_PATH=/api/v1/health/
LEDGEROS_TIMEOUT_SECONDS=5
```

If the sibling LedgerOS repo uses a different API client, change only:
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY` if LedgerOS requires bearer auth

| Variable | Group | Purpose | Required | Dev-only sample | When to change |
| --- | --- | --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | Django/runtime | Secret key used by PropertyLedger. | Yes | Yes | Change before any shared, staging, or production use. |
| `DJANGO_DEBUG` | Django/runtime | Enables local Django debug behavior. | Yes | Yes | Change to `false` outside local development. |
| `DJANGO_ALLOWED_HOSTS` | Django/runtime | Hostnames Django accepts requests for. | Yes | Yes | Change when you use different hostnames or expose the app externally. |
| `DATABASE_ENGINE` | PropertyLedger database | Django database backend. | Yes | Yes | Change only if you switch away from PostgreSQL. |
| `DATABASE_NAME` | PropertyLedger database | PropertyLedger database name. | Yes | Yes | Change if you rename the local database. |
| `DATABASE_USER` | PropertyLedger database | PropertyLedger database user. | Yes | Yes | Change if your database credentials differ. |
| `DATABASE_PASSWORD` | PropertyLedger database | PropertyLedger database password. | Yes | Yes | Change if your database credentials differ. |
| `DATABASE_HOST` | PropertyLedger database | Database host or Docker Compose service name. | Yes | Yes | Change if the database host or service name changes. |
| `DATABASE_PORT` | PropertyLedger database | Database port. | Yes | Yes | Change if PostgreSQL listens on a different port. |
| `LEDGEROS_BASE_URL` | LedgerOS connection | Base URL PropertyLedger uses to reach LedgerOS. In full-stack Docker mode, use `http://ledgeros-web:8000`. | Yes for full-stack | Yes | Change when the LedgerOS host or service name changes. |
| `LEDGEROS_CLIENT_ID` | LedgerOS authentication | Client ID sent with signed LedgerOS requests. Use the value configured in the LedgerOS repo, for example `propertyledger` if that client exists there. | Yes for full-stack | Yes | Change to match the client ID configured in LedgerOS. |
| `LEDGEROS_HMAC_SECRET` | LedgerOS authentication | Shared secret value used to sign LedgerOS requests. It is not a variable name. | Yes for full-stack | Yes | Change to the secret value configured for the LedgerOS client. |
| `LEDGEROS_API_KEY` | LedgerOS authentication | Optional bearer token for LedgerOS requests. Leave blank unless LedgerOS explicitly requires bearer auth. | No | Yes | Change only if your LedgerOS deployment requires bearer auth. |
| `LEDGEROS_HEALTH_PATH` | Integration/idempotency behavior | LedgerOS health endpoint path used by the health check. | Yes for full-stack | Yes | Change when the LedgerOS health route changes. |
| `LEDGEROS_TIMEOUT_SECONDS` | Integration/idempotency behavior | Timeout for LedgerOS health requests. | Yes for full-stack | Yes | Change if LedgerOS is slower or faster in your environment. |

## Included docs

- `docs/propertyledger-prd.md` — product requirements document.
- `docs/propertyledger-implementation-epics.md` — buildable implementation epics for AI agents.
- `docs/ledgeros-integration-contract.md` — local Epic 1 LedgerOS integration contract.
- `docs/epic-1-lessons-learned.md` — Epic 1 retrospective and setup notes for later epics.
- `docs/epic-2.md` — Epic 2 runbook for setup and CRUD workflows.
- `CLAUDE.md` — guidance for AI agents working on the PropertyLedger repo.

## Core architecture decision

PropertyLedger should be a separate repo from LedgerOS and interact with LedgerOS through a clean adapter/API boundary.

```text
PropertyLedger domain
  -> Accounting adapter interface
  -> LedgerOS adapter implementation
  -> LedgerOS HTTP API/services
```

PropertyLedger must not import LedgerOS models, call LedgerOS Python services directly, or write to the LedgerOS database.

## MVP product direction

PropertyLedger is accounting-first. It targets property managers managing units on behalf of owners.

MVP includes:

- properties, units, tenants, leases, owners;
- recurring base rent generation plus manual tenant charges;
- tenant payments and tenant ledger visibility;
- vendor bills and maintenance expense tracking;
- debt-service and credit-card account support;
- owner statements;
- guided banking workflows through controlled LedgerOS APIs;
- property-management reports that reconcile to LedgerOS posted records;
- documented API/adapter path for sophisticated users and agent-built connectors.

Deferred or post-MVP:

- tenant portal;
- online rent collection;
- automated bank-feed ingestion;
- full maintenance work orders;
- owner portal;
- automated management-fee calculation;
- multi-entity owner books;
- QuickBooks/Xero connectors;
- check writing implementation, although the data model must reserve a drop-in path for it.

## Next recommended step

Start with the Epic 1 runtime setup:

1. Clone the LedgerOS repo in a sibling directory. The bundled compose file expects it at `../ledgeros_v2`.
2. Clone the PropertyLedger repo.
3. If you want to customize the environment, copy `.env.fullstack.example` to `.env` and edit the LedgerOS client values there.
4. Run `make up-full`.
5. Run `make migrate-full`.
6. Create the admin users:
   - PropertyLedger:
     ```bash
     docker compose -f docker-compose.yml -f docker-compose.ledgeros.yml exec propertyledger-web python manage.py createsuperuser
     ```
   - LedgerOS:
     ```bash
     cd ../ledgeros_v2
     docker compose exec web python manage.py createsuperuser
     ```
7. Run `make smoke-full`.
8. Open the admin screens:
   - PropertyLedger: `http://localhost:8000/admin/`
   - LedgerOS: `http://localhost:8001/admin/`
9. Open the setup screen at `http://localhost:8000/`.

The real LedgerOS setup uses the current LedgerOS API health route at `/api/v1/health/`.

Before coding, an AI agent should read:

1. `CLAUDE.md`
2. `docs/propertyledger-prd.md`
3. `docs/propertyledger-implementation-epics.md`
4. The LedgerOS docs that define API authentication, idempotency, accounting invariants, reporting invariants, and epic implementation discipline.
