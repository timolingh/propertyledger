# PropertyLedger Quick Start

## Before you start

You need:

- Docker and Docker Compose;
- a running LedgerOS endpoint;
- the PropertyLedger repository.

The setup path is a prerequisite for using the app meaningfully. If you only want to boot the containers, you can stop after `make up`; if you want a usable PropertyLedger environment, you must also complete the admin setup steps.

For the detailed admin checklist, see [Admin Setup Guide](./admin-setup.md).

## 1. Configure the environment

Copy `.env.example` to `.env` if you want a local file to edit.

Set the LedgerOS values:

- `LEDGEROS_BASE_URL`
- `LEDGEROS_CLIENT_ID`
- `LEDGEROS_HMAC_SECRET`

Optional but useful:

- `LEDGEROS_HOST_HEADER`
- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

## 2. Start the app

```bash
make up
```

## 3. Run migrations and bootstrap

```bash
make migrate
```

## 4. Run the smoke checks

```bash
make smoke
```

## 5. Create an admin user

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py createsuperuser
```

## 6. Open the app

- Workflow home after login: `http://localhost:8000/home/`
- Admin setup page: `http://localhost:8000/`
- Admin: `http://localhost:8000/admin/`

PropertyLedger uses `propertyledger_sessionid` and `propertyledger_csrftoken`
cookies so logging into LedgerOS on another localhost port does not overwrite
its session or form tokens. After upgrading from the shared default cookie names,
log into PropertyLedger again and reload any previously open forms before submitting.

## 7. First checks

After the app starts, confirm:

1. the local health check is healthy;
2. the LedgerOS health check is healthy for your configured endpoint;
3. the setup screen saves your connection settings;
4. the required account mappings are present;
5. the setup smoke test passes and is recorded on the setup screen.
6. sign in with an explicitly assigned PropertyLedger role and confirm the shared home and sidebar appear. Unassigned accounts receive access guidance; Django staff status alone does not assign a workflow role.
7. as an administrator, open `/payments/workflow-authorizations/` and explicitly assign the intended bill approvers and vendor-payment users. Migration creates no automatic financial grants.
8. open `/payments/maintenance/` as an administrator, property manager, or bookkeeper; create a request and confirm it can move from Open to Triaged without LedgerOS connectivity.
9. open a maintenance request and either create a linked vendor bill as an administrator/bookkeeper or link a compatible existing bill as a property manager. Confirm the maintenance state remains unchanged.

## Typical development commands

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test
make check
```

## Beta testing

If you are doing user beta testing, start with the beta guide:

- [Beta Testing Guide](./beta-testing.md)

Use the beta seed command first, then complete the admin setup prerequisites before following the manual role checklists in the guide. The beta guide assumes the admin setup guide has already been completed.
If LedgerOS web is not running yet, the beta seed command will warn and continue instead of failing, and you can run `make smoke` after both stacks are up.

## If something fails

When upgrading for bill payment status, deploy the matching LedgerOS code and
apply its migrations first. See the [Technical Manual](./technical-manual.md)
for the upgrade and legacy credit-card reconciliation commands. The bill list
shows Unavailable if the upstream bill-read API cannot be reached.

- Check the `.env` values first.
- Make sure LedgerOS is already running.
- Verify the Docker containers are up.
- Re-run the smoke checks after fixing the issue.

## See also

- [Technical Manual](./technical-manual.md)
- [User Manual](./user-manual.md)
