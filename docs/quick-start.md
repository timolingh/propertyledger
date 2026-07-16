# PropertyLedger Quick Start

## Before you start

You need:

- Docker and Docker Compose;
- a running LedgerOS endpoint;
- the PropertyLedger repository.

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

- Main setup page: `http://localhost:8000/`
- Admin: `http://localhost:8000/admin/`

## 7. First checks

After the app starts, confirm:

1. the local health check is healthy;
2. the LedgerOS health check is healthy for your configured endpoint;
3. the setup screen saves your connection settings;
4. the required account mappings are present;
5. the setup smoke test passes.

## Typical development commands

```bash
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test
make check
```

## Beta testing

If you are doing user beta testing, start with the beta guide:

- [Beta Testing Guide](./beta-testing.md)

Use the beta seed command first, then follow the manual role checklists in the guide.

## If something fails

- Check the `.env` values first.
- Make sure LedgerOS is already running.
- Verify the Docker containers are up.
- Re-run the smoke checks after fixing the issue.

## See also

- [Technical Manual](./technical-manual.md)
- [User Manual](./user-manual.md)
