# Epic 9 Decision Record

Epic 9 in this repo covers roles, permissions, audit visibility, and the minimum production-readiness notes needed to ship the MVP safely.

## Decisions

| Area | Decision |
| --- | --- |
| Role model | Use five coarse roles: `admin`, `property_manager`, `bookkeeper`, `owner_viewer`, and `read_only_viewer`. |
| Permission source | Use Django groups plus view mixins for enforcement. |
| Access model | Admin is the broadest role. Property managers cover property operations. Bookkeepers cover accounting workflows. Owner viewers and read-only viewers are reporting-oriented. |
| Audit model | Record successful workflow actions and failed login/access attempts in an immutable audit log. |
| Audit access | Expose recent audit activity in the app and in Django admin as read-only. |
| Production notes | Document environment variables, deployment checks, and secret-handling expectations in repo docs rather than introducing new infrastructure. |

## Roadmap Items

- Fine-grained permissions remain out of scope for the MVP.
- Approval chains remain deferred.
- Owner portal remains deferred.
- Tenant portal remains deferred.
- Enterprise SSO remains deferred.
- Billing and subscription management remain deferred.
- Import/export enhancements beyond the current basics remain a later roadmap item.

## Traceability

- Epic definition: [`docs/propertyledger-implementation-epics.md`](./propertyledger-implementation-epics.md)
- Audit log view: `Audit log` in the LedgerOS app
- Role helpers: `ledgeros/roles.py`
- Permission helpers: `ledgeros/permissions.py`
- Audit helpers: `ledgeros/audit.py`

## Operational Guidance

- Assign users to Django groups to grant roles.
- Keep the audit log immutable.
- Use the deployment checklist and environment variable guidance before production rollout.
- Store secrets in environment variables and never hard-code secrets into settings or source files.

## Environment Variables

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
- `LEDGEROS_API_KEY`
- `LEDGEROS_HEALTH_PATH`
- `LEDGEROS_TIMEOUT_SECONDS`

## Deployment Checklist

- Confirm `DJANGO_DEBUG` is off in production.
- Set a non-default `DJANGO_SECRET_KEY`.
- Point database settings at the production database.
- Configure the LedgerOS connection settings and health endpoint.
- Verify role groups exist after migrations.
- Verify the audit log page is reachable for reporting roles.
- Run migrations before serving traffic.
- Run the application health checks and a smoke test before enabling users.

## Secret Handling

- Keep application secrets in the environment, not in Git.
- Rotate the Django secret key and LedgerOS secret values through the deployment platform or secret store.
- Avoid printing secrets in logs, template output, or error messages.
