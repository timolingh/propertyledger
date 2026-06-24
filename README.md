# PropertyLedger

**PropertyLedger** is a real estate accounting client for LedgerOS.

It is intended to be built as a separate application from LedgerOS. PropertyLedger owns property-management context such as properties, units, tenants, leases, owners, rent roll, maintenance categories, and owner statements. LedgerOS remains the accounting system of record for invoices, bills, payments, journals, banking, reconciliation, reports, and audit history.

## Current package status

This repository now includes the Epic 1 through Epic 3 Django foundation for PropertyLedger:

- Django + Django REST Framework backend;
- PostgreSQL-backed Docker Compose local setup that talks to a running LedgerOS endpoint;
- LedgerOS adapter boundary with real LedgerOS as the only integration target;
- deterministic local and LedgerOS health checks;
- locked `LedgerOSSyncRecord` schema and uniqueness constraints;
- admin/setup screen plus Epic 2 CRUD pages for properties, units, owners, tenants, and leases;
- Epic 3 tenant-charge workflow for base rent generation and manual charges.

## Environment variables

Use [`.env.example`](./.env.example) as the single env template. Leave the LedgerOS values blank for PropertyLedger-only local work, or fill them in with the LedgerOS-enabled values below.

Warning: `LEDGEROS_BASE_URL` should point at the running LedgerOS endpoint, such as `http://host.docker.internal:8001` when LedgerOS is running on your host alongside Docker Compose.

Quick LedgerOS-enabled starter values:

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

If the sibling LedgerOS repo uses a different API client, change only:
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`
- `LEDGEROS_API_KEY` if LedgerOS requires bearer auth

Where to get the LedgerOS values:

- `LEDGEROS_BASE_URL`: the URL where LedgerOS is already running, such as `http://host.docker.internal:8001` for a host-running local LedgerOS instance or your deployed LedgerOS URL.
- `LEDGEROS_HOST_HEADER`: optional `Host` header override to send when the LedgerOS server expects a different host name than the connection URL, such as `localhost:8001` for a host-run local stack.
- `LEDGEROS_CLIENT_ID`: the client id defined in the LedgerOS `api_clients.yml` file, such as `api_full`.
- `LEDGEROS_HMAC_SECRET`: the matching secret value for that client, such as the LedgerOS env var `LEDGEROS_API_CLIENT_FULL_SECRET`.
- `LEDGEROS_API_KEY`: only if your LedgerOS deployment explicitly requires bearer auth.

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
| `LEDGEROS_BASE_URL` | LedgerOS connection | Base URL PropertyLedger uses to reach LedgerOS. For a local LedgerOS instance running on the host, use `http://host.docker.internal:8001`. | Yes for LedgerOS setup | Yes | Change when the LedgerOS host or deployment URL changes. |
| `LEDGEROS_HOST_HEADER` | LedgerOS connection | Optional `Host` header override sent to LedgerOS. Leave blank for normal deployments; set it only when the server expects a different host name than the URL used to connect. | No | Yes | Change when the remote server rejects the default host header. |
| `LEDGEROS_CLIENT_ID` | LedgerOS authentication | Client ID sent with signed LedgerOS requests. Use the value configured in the LedgerOS repo, for example `api_full` if that client exists there. | Yes for LedgerOS setup | Yes | Change to match the client ID configured in LedgerOS. |
| `LEDGEROS_HMAC_SECRET` | LedgerOS authentication | Shared secret value used to sign LedgerOS requests. It is not a variable name. | Yes for LedgerOS setup | Yes | Change to the secret value configured for the LedgerOS client. |
| `LEDGEROS_API_KEY` | LedgerOS authentication | Optional bearer token for LedgerOS requests. Leave blank unless LedgerOS explicitly requires bearer auth. | No | Yes | Change only if your LedgerOS deployment requires bearer auth. |
| `LEDGEROS_HEALTH_PATH` | Integration/idempotency behavior | LedgerOS health endpoint path used by the health check. | Yes for LedgerOS setup | Yes | Change when the LedgerOS health route changes. |
| `LEDGEROS_TIMEOUT_SECONDS` | Integration/idempotency behavior | Timeout for LedgerOS health requests. | Yes for LedgerOS setup | Yes | Change if LedgerOS is slower or faster in your environment. |

## Included docs

- `docs/propertyledger-prd.md` — product requirements document.
- `docs/propertyledger-implementation-epics.md` — buildable implementation epics for AI agents.
- `docs/ledgeros-integration-contract.md` — local Epic 1 LedgerOS integration contract.
- `docs/epic-1-lessons-learned.md` — Epic 1 retrospective and setup notes for later epics.
- `docs/epic-2-lessons-learned.md` — Epic 2 retrospective and workflow notes for later epics.
- `docs/epic-3-lessons-learned.md` — Epic 3 retrospective and charge-workflow notes for later epics.
- `docs/epic-1.md` — Epic 1 runbook for setup and verification.
- `docs/epic-2.md` — Epic 2 runbook for setup and CRUD workflows.
- `docs/epic-3.md` — Epic 3 runbook for rent generation and tenant charges.
- `CLAUDE.md` — guidance for AI agents working on the PropertyLedger repo.

## Testing

Always run automated tests in Docker containers. Use the compose commands below from the repo root:

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test
make check
```

Do not assume host Python or host-installed Django dependencies are available.

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

## Development bootstrap

PropertyLedger is started on its own. LedgerOS is assumed to already be running at a separate endpoint.

Bootstrap principle: keep the user in PropertyLedger for setup and seed the LedgerOS prerequisites from the PropertyLedger-side bootstrap flow whenever possible. Avoid making the user switch into the LedgerOS repo or UI just to complete setup that PropertyLedger already knows is required.

1. Copy `.env.example` to `.env` if you want a local file to edit.
2. Set the LedgerOS values in `.env` or export them in your shell:
   - `LEDGEROS_BASE_URL`
   - `LEDGEROS_CLIENT_ID`
   - `LEDGEROS_HMAC_SECRET`
3. If you already have those values in another env file, point the bootstrap script at it:
   ```bash
   LEDGEROS_SOURCE_ENV_FILE=/path/to/ledgeros.env ./scripts/dev-bootstrap.sh
   ```
4. Otherwise, export the values in your shell and run:
   ```bash
   ./scripts/dev-bootstrap.sh
   ```
5. The script uses the current shell environment plus any `.env` file you already have, boots the LedgerOS sample chart of accounts plus an open accounting period when the sibling LedgerOS repo is present, persists the selected LedgerOS entity and accounting period back into PropertyLedger, starts the PropertyLedger containers, runs migrations, and bootstraps the saved connection settings plus the required account mappings.
6. Open the setup screen at `http://localhost:8000/` to finish the remaining PropertyLedger-specific setup. The LedgerOS entity and accounting period should already be selected by the bootstrap, so you should not need to pick them manually.
7. Create the admin user if you do not already have one:
   ```bash
   docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py createsuperuser
   ```
8. Open the admin screen at `http://localhost:8000/admin/`.

Before coding, an AI agent should read:

1. `CLAUDE.md`
2. `docs/propertyledger-prd.md`
3. `docs/propertyledger-implementation-epics.md`
4. The LedgerOS docs that define API authentication, idempotency, accounting invariants, reporting invariants, and epic implementation discipline.
