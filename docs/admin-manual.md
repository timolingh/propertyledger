# PropertyLedger deployment and administration manual

This manual is for the administrator who deploys, operates, upgrades, and recovers PropertyLedger and its LedgerOS v2 accounting backend at Forte. Bookkeepers and property managers should use the [user manual](user-manual.md).

The production host is a **2018 Intel MacBook Pro at the Forte office**, running its supported macOS installation and **Docker Desktop with Docker Compose**. Both applications use Gunicorn and separate PostgreSQL 16 containers. A **Caddy container is the only service that publishes web ports**. Employees access the applications exclusively through the authorized internal LAN:

| Application | Production address |
| --- | --- |
| PropertyLedger | `https://propertyledger.forteresources.com` |
| LedgerOS v2 | `https://ledgeros.forteresources.com` |

PropertyLedger retains its controlled accounting API boundary with LedgerOS. Application and database containers have no published host ports. This installation needs no cloud server, internet-facing NAT, router port forwarding, Cloudflare Tunnel, or separate virtualization product. Outbound connectivity is still needed for image/package downloads and, if selected, certificate issuance and renewal.

## Find the procedure you need

- [Prepare the MacBook](#prepare-the-macbook)
- [Deployment prerequisites](#deployment-prerequisites)
- [Network and proxy configuration](#network-and-proxy-configuration)
- [Production configuration](#production-configuration)
- [Caddy and certificates](#caddy-and-certificates)
- [First deployment](#first-deployment)
- [Connect the accounting books](#connect-the-accounting-books)
- [Users and access](#users-and-access)
- [Release acceptance](#release-acceptance)
- [Routine operations](#routine-operations)
- [Backups and recovery](#backups-and-recovery)
- [Upgrades and rollback](#upgrades-and-rollback)
- [Troubleshooting](#troubleshooting)
- [Local demonstration](#local-demonstration)

## Prepare the MacBook

Inventory the actual host before installing production data:

```sh
sw_vers
system_profiler SPHardwareDataType
df -h /
docker version
docker compose version
```

Confirm that this Mac can run a macOS version supported by a maintained Docker Desktop release. A 2018 model designation alone does not establish compatibility. Verify the Intel installer and company licensing eligibility against [Docker's current Mac requirements](https://docs.docker.com/desktop/setup/install/mac-install/); obtain any required company subscription before use.

Keep the workstation connected to power, preferably through wired Ethernet, with adequate ventilation and a healthy battery. Disable automatic system sleep while on power and enable Docker Desktop startup at the deployment user's login. For a 16 GB machine, use roughly four CPUs and 6 GB RAM as an initial Docker allocation, then adjust to measured application and database usage.

Test recovery after a full reboot, including FileVault unlock, macOS login, Docker Desktop startup, the reserved LAN address, and all three Compose stacks. `restart: unless-stopped` takes effect after Docker is running; it does not unlock or log into macOS. Document who can restore service after a power interruption. This is one host, so hardware failure or host maintenance interrupts both applications.

Existing hardware can avoid a monthly hosting bill. Electricity, backup storage, replacement hardware, and any applicable Docker Desktop licensing remain operating costs.

## Deployment prerequisites

**The checked-in Docker configuration is for development. Complete the production packaging below before admitting production users.** The production settings, images, and configuration examples in this manual describe the deployment to prepare; they are not an already installed or tested production package.

| Area | Current repository behavior | Required production preparation |
| --- | --- | --- |
| Application server | Both Dockerfiles and development Compose files run `manage.py runserver`. Neither application declares Gunicorn. | Include a tested, pinned Gunicorn dependency in each release image. Django excludes `runserver` from production use; see the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/). |
| Django release | PropertyLedger requires `Django>=5.0,<5.1`. | Upgrade and test against a supported release. Django 5.0 security support ended April 2, 2025; consult the [support table](https://www.djangoproject.com/download/#supported-versions) for each release. |
| HTTPS settings | PropertyLedger has no production settings module. LedgerOS has `config.settings.production` with trusted-proxy and secure-cookie settings. | Supply the production settings described below, including each application's exact origin and password policy. Environment variables work only when settings code reads them. |
| Static files | PropertyLedger defines `STATIC_ROOT`; LedgerOS's current production settings do not. Neither declares WhiteNoise. | Add and configure WhiteNoise, define static roots, and collect static files into both release images. Test CSS and admin assets with debug disabled. |
| Images and secrets | Both Dockerfiles copy their build context, and neither repository currently supplies a `.dockerignore`. | Exclude `.env`, `.env.*`, `.git`, credentials, dumps, local databases, and `.demo/` from build contexts. Supply production secrets only at runtime. |
| Development networking | Development Compose publishes app ports; LedgerOS also publishes PostgreSQL. | Use standalone production Compose files with no application or database `ports` entries. Attach only web services to `forte`. |
| Persistence and operation | Each application has a PostgreSQL volume. | Keep separate persistent volumes, add health checks/restart policies, preserve Caddy state, and prove coordinated recovery. |

The release owner supplies a matched pair of tested application images for `linux/amd64`, source commit identifiers, migration notes, and an approved Caddy image. Use immutable image digests or release tags that are never overwritten. Obtain images through an approved registry or transfer/load the exact images when necessary. Do not install packages when containers start.

## Network and proxy configuration

Request a DHCP reservation for the MacBook's production LAN interface and create both **internal** DNS A records pointing to that reserved address. `172.16.2.100` below is an example, not an assigned address. No public A or AAAA records are required. Public DNS TXT updates may be needed for DNS-01 certificate validation.

| Connection | Destination | Access rule |
| --- | --- | --- |
| Employee browsers | Reserved MacBook LAN IP, TCP 443 | Authorized Forte LAN clients only. |
| HTTP redirect | Same IP, TCP 80 | Same permitted LAN sources; redirects to HTTPS after setup. |
| Caddy | `propertyledger-web:8000`, `ledgeros-web:8000` | Shared private Docker network `forte`. |
| PropertyLedger | `https://ledgeros.forteresources.com` | HTTPS through Caddy, with matching HMAC API credentials. |
| Each web service | Its own PostgreSQL container, TCP 5432 | Its own private Compose network; no database attaches to `forte`. |

Use host and network firewall controls to restrict inbound ports 80/443. Binding Caddy to a LAN address is not an access policy. Do not create internet-facing port forwarding. VPN access is excluded unless Forte explicitly adds the relevant VPN networks to the authorized policy. Verify the policy from both an allowed workstation and an excluded network.

Ask IT for the reserved address, the two internal DNS records, the authoritative public DNS provider and API availability, whether Forte has a trusted company certificate authority, and the permitted LAN ranges. The DNS provider, certificate method, actual macOS compatibility, reserved IP, and backup destination remain deployment decisions until verified; do not substitute sample values for those answers.

Create the shared network once:

```sh
docker network create forte
```

If it already exists, inspect it before reuse. Only Caddy and the two web services belong on it. Each application's default network holds its own database. PropertyLedger must never connect directly to the LedgerOS database.

The Caddy example gives Caddy the Docker DNS aliases `propertyledger.forteresources.com` and `ledgeros.forteresources.com`. Containers on `forte` therefore reach the correct HTTPS virtual host without routing back through the MacBook's LAN address. Employee browsers continue using company DNS. Certificate validation still uses the full production hostname.

Caddy preserves the incoming host and API paths and supplies forwarding headers. Keep its default protection against untrusted client forwarding headers; do not configure arbitrary trusted proxies. Preserve `X-LedgerOS-*` and `Idempotency-Key`, and do not add automatic retries for accounting POST requests. See [Caddy's reverse proxy behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## Production configuration

### Files and command conventions

Keep production checkouts and credentials separate from development:

```text
~/forte-server/
  propertyledger/
    docker-compose.prod.yml
    .env
  ledgeros_v2/
    docker-compose.prod.yml
    .env
  caddy/
    docker-compose.yml
    Caddyfile
    .env
    Dockerfile       # only when a DNS plugin must be built
    certs/           # only for a company-issued certificate
  backups/           # protected staging; copy encrypted backups off-host
```

For an initial installation:

```sh
mkdir -p ~/forte-server
cd ~/forte-server
git clone https://github.com/timolingh/propertyledger.git
git clone https://github.com/timolingh/ledgeros_v2.git
mkdir -p caddy backups
```

Select approved source releases, then save the example configurations in those locations. **Do not merge production files with the development Compose files**, which would retain development mounts, commands, or published ports. Keep credentials out of Git and build contexts.

Define these functions in your administration shell. They select fixed files and projects regardless of the shell's current directory:

```sh
forte_root="$HOME/forte-server"
pl() {
  docker compose --project-name propertyledger-production \
    --env-file "$forte_root/propertyledger/.env" \
    -f "$forte_root/propertyledger/docker-compose.prod.yml" "$@"
}
lo() {
  docker compose --project-name ledgeros-production \
    --env-file "$forte_root/ledgeros_v2/.env" \
    -f "$forte_root/ledgeros_v2/docker-compose.prod.yml" "$@"
}
caddy_stack() {
  docker compose --project-name forte-caddy \
    --env-file "$forte_root/caddy/.env" \
    -f "$forte_root/caddy/docker-compose.yml" "$@"
}
```

Keep these project names stable and record actual volume names using `docker volume ls` and `docker volume inspect`. Before moving an existing installation into this layout, identify its volumes and arrange a tested migration. A different project can create an empty database instead of attaching existing data.

### Application settings and static files

Each release image contains Gunicorn, WhiteNoise, code, migrations, and collected static assets. PropertyLedger also needs a new `propertyledger.production_settings` module. For example:

```python
# propertyledger/production_settings.py
from .settings import *

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = ["https://propertyledger.forteresources.com"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
```

These are code additions to package, not environment variables currently supported by the application. Extend LedgerOS's `config.settings.production` similarly, using origin `https://ledgeros.forteresources.com`, its own static root and password policy, and WhiteNoise immediately after SecurityMiddleware. Keep its existing proxy/secure-cookie settings.

The release build must run `python manage.py collectstatic --noinput` with the production static configuration and non-production build settings/secrets, and retain the resulting assets in the image. WhiteNoise serves `/static/` through Gunicorn and Caddy. Running `collectstatic` in a disposable container without a retained volume does not update the running image. No source or static-directory bind mounts are needed here. See [WhiteNoise's Django configuration](https://whitenoise.readthedocs.io/en/stable/django.html).

Use non-root application users. Verify settings with `check --deploy` and browser form submission. Enable HSTS only after HTTPS and renewal operate reliably. When using a company or Caddy CA, install the public root/intermediate chain into PropertyLedger's image trust store; browsers and containers both need trust. Never disable TLS verification.

### PropertyLedger Compose and environment

Save as `propertyledger/docker-compose.prod.yml`:

```yaml
services:
  propertyledger-db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DATABASE_NAME:?Set DATABASE_NAME}
      POSTGRES_USER: ${DATABASE_USER:?Set DATABASE_USER}
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD:?Set DATABASE_PASSWORD}
    volumes:
      - propertyledger_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: [CMD-SHELL, 'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"']
      interval: 5s
      timeout: 5s
      retries: 10
  propertyledger-web:
    image: ${PROPERTYLEDGER_IMAGE:?Set PROPERTYLEDGER_IMAGE}
    restart: unless-stopped
    env_file: .env
    command: [gunicorn, propertyledger.wsgi:application, --bind, "0.0.0.0:8000", --workers, "3", --access-logfile, "-", --error-logfile, "-"]
    networks:
      default: {}
      forte:
        aliases: [propertyledger-web]
    healthcheck:
      test: [CMD, python, -c, "from urllib.request import Request,urlopen; urlopen(Request('http://127.0.0.1:8000/api/health/local/', headers={'Host':'propertyledger.forteresources.com','X-Forwarded-Proto':'https'}), timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    depends_on:
      propertyledger-db:
        condition: service_healthy
networks:
  default:
    internal: true
  forte:
    external: true
volumes:
  propertyledger_postgres_data:
```

Save as `propertyledger/.env`, replacing every `REPLACE_` value:

```dotenv
PROPERTYLEDGER_IMAGE=REPLACE_WITH_IMMUTABLE_PROPERTYLEDGER_IMAGE
DJANGO_SETTINGS_MODULE=propertyledger.production_settings
DJANGO_SECRET_KEY=REPLACE_WITH_PROPERTYLEDGER_SECRET
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=propertyledger.forteresources.com
DATABASE_ENGINE=django.db.backends.postgresql
DATABASE_NAME=propertyledger
DATABASE_USER=propertyledger
DATABASE_PASSWORD=REPLACE_WITH_PROPERTYLEDGER_DB_PASSWORD
DATABASE_HOST=propertyledger-db
DATABASE_PORT=5432
LEDGEROS_BASE_URL=https://ledgeros.forteresources.com
LEDGEROS_HOST_HEADER=
LEDGEROS_CLIENT_ID=api_full
LEDGEROS_HMAC_SECRET=REPLACE_WITH_SHARED_API_SECRET
LEDGEROS_API_KEY=
LEDGEROS_HEALTH_PATH=/api/v1/health/
LEDGEROS_TIMEOUT_SECONDS=5
```

Leave the host-header override blank. Retain the HTTPS LedgerOS hostname, not `localhost`, `host.docker.internal`, or a direct HTTP service URL. The `DJANGO_SETTINGS_MODULE` value selects production settings for management commands and Gunicorn.

### LedgerOS Compose and environment

Save as `ledgeros_v2/docker-compose.prod.yml`:

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:?Set POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER:?Set POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: [CMD-SHELL, 'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"']
      interval: 5s
      timeout: 5s
      retries: 10
  web:
    image: ${LEDGEROS_IMAGE:?Set LEDGEROS_IMAGE}
    restart: unless-stopped
    env_file: .env
    command: [gunicorn, config.wsgi:application, --bind, "0.0.0.0:8000", --workers, "3", --access-logfile, "-", --error-logfile, "-"]
    networks:
      default: {}
      forte:
        aliases: [ledgeros-web]
    healthcheck:
      test: [CMD, python, -c, "from urllib.request import Request,urlopen; urlopen(Request('http://127.0.0.1:8000/api/v1/health/', headers={'Host':'ledgeros.forteresources.com','X-Forwarded-Proto':'https'}), timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    depends_on:
      db:
        condition: service_healthy
networks:
  default:
    internal: true
  forte:
    external: true
volumes:
  postgres_data:
```

Save as `ledgeros_v2/.env`:

```dotenv
LEDGEROS_IMAGE=REPLACE_WITH_IMMUTABLE_LEDGEROS_IMAGE
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=REPLACE_WITH_LEDGEROS_SECRET
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=ledgeros.forteresources.com
POSTGRES_DB=ledgeros
POSTGRES_USER=ledgeros
POSTGRES_PASSWORD=REPLACE_WITH_LEDGEROS_DB_PASSWORD
POSTGRES_HOST=db
POSTGRES_PORT=5432
LEDGEROS_API_CLIENTS_CONFIG=/app/api_clients.yml
LEDGEROS_API_CLIENT_FULL_SECRET=REPLACE_WITH_SHARED_API_SECRET
```

Use tested PostgreSQL image digests in the final release configuration. Three Gunicorn workers are an initial example; measure CPU and memory use on the actual MacBook before adjusting concurrency.

### API credentials and secret handling

Use independent random Django secret keys and database passwords. The supplied LedgerOS `api_clients.yml` enables `api_full`, with `secret_env` set to `LEDGEROS_API_CLIENT_FULL_SECRET`. Its value must equal PropertyLedger's `LEDGEROS_HMAC_SECRET`. The client ID is a configured identifier, not a username. Keep host time synchronized for signed requests.

The current scopes are `customers`, `vendors`, `invoices`, `bills`, `payments`, `banking`, `sync_events`, and `credits`. Allowed events are `customer.upsert_requested`, `vendor.upsert_requested`, `invoice.post_requested`, `bill.post_requested`, `payment.post_requested`, `bank.deposit_requested`, `bank.withdrawal_requested`, `sync.event_received`, `credit.post_requested`, and `refund.post_requested`. Preserve the permissions required by deployed workflows. Health does not prove permission to post.

Leave PropertyLedger's `LEDGEROS_API_KEY` empty for the supplied HMAC client, which has no API-key configuration. Protect all three `.env` files with owner-only permissions. Do not commit or build credentials into images. Treat rendered Compose configuration and container inspection output as sensitive; shell variables can override environment-file interpolation under [Docker's precedence rules](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/).

## Caddy and certificates

### Caddy container

Save as `caddy/docker-compose.yml`:

```yaml
services:
  caddy:
    image: ${CADDY_IMAGE:?Choose an approved Caddy image}
    restart: unless-stopped
    env_file: .env
    ports:
      - "${LAN_IP:?Set reserved LAN_IP}:80:80"
      - "${LAN_IP:?Set reserved LAN_IP}:443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      forte:
        aliases:
          - propertyledger.forteresources.com
          - ledgeros.forteresources.com
networks:
  forte:
    external: true
volumes:
  caddy_data:
  caddy_config:
```

Save as `caddy/.env`:

```dotenv
LAN_IP=172.16.2.100
CADDY_IMAGE=REPLACE_WITH_APPROVED_CADDY_IMAGE
```

Replace the example IP with IT's reserved address. For company or internal CA use, select an approved Caddy 2 image. DNS-01 needs a custom image containing the actual provider's plugin. Preserve `/data` and `/config` volumes. Do not publish Caddy's administration API.

### Initial routing check

An optional HTTP-only Caddyfile can verify routing with non-sensitive test data:

```caddy
http://propertyledger.forteresources.com {
    reverse_proxy propertyledger-web:8000
}
http://ledgeros.forteresources.com {
    reverse_proxy ledgeros-web:8000
}
```

Use a separate test configuration for this phase. Production Django settings enforce HTTPS and secure cookies, so HTTP-only testing cannot validate production login. Replace this file with one of the HTTPS configurations below before using production credentials or financial data.

### Preferred certificate method using DNS validation

Use Let's Encrypt DNS-01 when IT can supply narrowly scoped API credentials for the authoritative public DNS provider and a compatible Caddy plugin. Identify that provider with `dig NS forteresources.com +short` and confirm it with IT. Public TXT validation allows private applications without inbound internet access; see [Let's Encrypt DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge).

Build and approve a provider-specific Caddy image, then set `CADDY_IMAGE` to that image. The following Dockerfile is **only for an existing Cloudflare DNS provider**, not an instruction to move DNS or create a tunnel:

```dockerfile
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare
FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

Pin the approved builder/runtime images and plugin revision in the release build. For this Cloudflare example, add `CLOUDFLARE_API_TOKEN` to the protected `caddy/.env`; `env_file` passes it to Caddy. Scope the token to DNS editing and zone reading for the required zone, following the [plugin's configuration](https://github.com/caddy-dns/cloudflare). Use the real provider's plugin and credential fields when it differs.

The Cloudflare example `Caddyfile` is:

```caddy
{
    acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
}
propertyledger.forteresources.com {
    @private_api path /api/health/* /api/v1/sync-events/
    respond @private_api 404
    reverse_proxy propertyledger-web:8000
}
ledgeros.forteresources.com {
    reverse_proxy ledgeros-web:8000
}
```

Allow outbound DNS and HTTPS to the provider and certificate authority. Verify issuance, automatic renewal, and expiry monitoring. Public certificate hostnames can appear in Certificate Transparency logs. The public DNS provider and plugin remain unselected until IT confirms them.

### Existing Forte certificate authority

If Forte operates a CA already trusted by employee workstations, generate a private key and CSR locally with both application names as Subject Alternative Names. Send only the CSR to IT. Obtain the signed certificate and intermediate chain, and keep the private key restricted on the MacBook.

Add `./certs:/certs:ro` to Caddy's Compose volumes. Place the certificate chain in `caddy/certs/forte.pem` and the key in `caddy/certs/forte.key`, then use:

```caddy
propertyledger.forteresources.com {
    tls /certs/forte.pem /certs/forte.key
    @private_api path /api/health/* /api/v1/sync-events/
    respond @private_api 404
    reverse_proxy propertyledger-web:8000
}
ledgeros.forteresources.com {
    tls /certs/forte.pem /certs/forte.key
    reverse_proxy ledgeros-web:8000
}
```

The certificate must cover both hostnames. Arrange renewal with IT and force a Caddy reload after replacing its files. Install the CA's public trust chain in the PropertyLedger image as well as employee trust stores.

### Caddy internal certificate authority

If DNS validation and a company CA are unavailable, use Caddy's internal CA:

```caddy
propertyledger.forteresources.com {
    tls internal
    @private_api path /api/health/* /api/v1/sync-events/
    respond @private_api 404
    reverse_proxy propertyledger-web:8000
}
ledgeros.forteresources.com {
    tls internal
    reverse_proxy ledgeros-web:8000
}
```

Have IT distribute only Caddy's public root certificate to the required workstation/browser trust stores and the PropertyLedger image. The default root certificate is at `/data/caddy/pki/authorities/local/root.crt` in the Caddy container; export that file with `caddy_stack cp caddy:/data/caddy/pki/authorities/local/root.crt ./forte-caddy-root.crt`. Never distribute the root private key. Preserve and securely back up Caddy's data volume; losing this CA can require redistributing trust. Caddy manages leaf renewal, while you monitor expiry and trust. See [Caddy automatic HTTPS and local trust](https://caddyserver.com/docs/automatic-https).

All final HTTPS examples block PropertyLedger's unauthenticated health and sync-event endpoints at the proxy. Use container health checks and administrative probes for monitoring. Expose those paths only after configuring a deliberate authenticated or source-restricted integration. LedgerOS API traffic from PropertyLedger must not require an interactive proxy login.

## First deployment

Complete the production image prerequisites, reserve the IP, create `forte`, choose a certificate method, and save the configuration files first. Initially restrict LAN ingress to the administrator's workstation using the approved firewall policy; preserve private application-to-LedgerOS connectivity for setup. Keep ordinary users out until acceptance is complete.

1. From `~/forte-server`, define the three shell functions above and protect the environment files:

   ```sh
   cd ~/forte-server
   chmod 600 propertyledger/.env ledgeros_v2/.env caddy/.env
   pl config --quiet
   lo config --quiet
   caddy_stack config --quiet
   pl pull
   lo pull
   caddy_stack pull
   ```

   Omit pulls for exact approved images already transferred and loaded. Validate a custom DNS plugin's presence in the selected Caddy image; the stock image cannot use an absent provider module.

2. Migrate and start LedgerOS first:

   ```sh
   lo up -d db
   lo run --rm web python manage.py migrate --noinput
   lo run --rm web python manage.py check --deploy
   lo run --rm web python manage.py createsuperuser
   lo up -d web
   lo ps
   ```

   Review deployment-check warnings and verify the web service becomes healthy. Its probe checks its database with the correct host/scheme headers. It does not validate HMAC permissions or accounting setup.

3. Migrate and start PropertyLedger:

   ```sh
   pl up -d propertyledger-db
   pl run --rm propertyledger-web python manage.py migrate --noinput
   pl run --rm propertyledger-web python manage.py check --deploy
   pl run --rm propertyledger-web python manage.py createsuperuser
   pl run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
   pl run --rm propertyledger-web python manage.py bootstrap_payment_workflow_settings
   pl up -d propertyledger-web
   pl ps
   ```

   `createsuperuser` prompts for initial credentials. Use separate accounts for the two applications; run it only when an initial account is needed. Do not run the demo mapping bootstrap.

4. Validate and start Caddy with the selected HTTPS Caddyfile:

   ```sh
   caddy_stack run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   caddy_stack up -d
   caddy_stack logs --tail=100 caddy
   ```

   For the Caddy internal CA, start Caddy to establish its CA, distribute the public root, and rebuild/redeploy PropertyLedger with that root trusted before its first LedgerOS HTTPS request. Company-issued certificates must already be mounted. DNS-01 needs the plugin, token, and outbound access. Resolve certificate errors before continuing.

5. Verify HTTPS from an authorized employee workstation, including PropertyLedger `/login/`, both `/admin/` pages, static assets, and a submitted login form. Confirm HTTP redirects. From PropertyLedger, test the actual LedgerOS hostname and certificate path:

   ```sh
   pl exec -T propertyledger-web python -c 'from urllib.request import urlopen; print(urlopen("https://ledgeros.forteresources.com/api/v1/health/", timeout=5).status)'
   ```

   Expect `200`. Caddy's Docker alias should resolve the hostname internally, and normal TLS validation must pass. A healthy endpoint is not proof that credentials can post accounting entries. Continue with book/account setup and release acceptance before allowing the full authorized LAN audience.

If a step fails, correct it before continuing. Development reset/seed scripts do not repair production. The static assets must already be present in the approved images; do not replace their build step with a disposable runtime collection.

## Connect the accounting books

Coordinate the entity, accounting period, and chart of accounts with the responsible bookkeeper. Deploy the LedgerOS release and all of its migrations before configuring PropertyLedger; do not copy database tables between applications or use demo data as real books.

1. In LedgerOS, establish the real accounting entity, chart of accounts, and appropriate open accounting period using its authorized administration process. Obtain the actual identifiers and names. PropertyLedger configuration does not create these accounting records.
2. Sign into PropertyLedger at `/admin/`. Review **LedgerOS connection settings**. Confirm the HTTPS base URL, `api_full` client ID, blank host header, `/api/v1/health/`, and timeout of five seconds. The secret fields store environment-variable **names**: `LEDGEROS_HMAC_SECRET` and `LEDGEROS_API_KEY`. Do not paste secret values into those fields.
3. Open **PropertyLedger setup** and save the actual entity ID/name and period ID/name. Create the account mappings against that same setup record. The required mapping keys are:

   | Mapping key | Intended account category |
   | --- | --- |
   | `operating_bank_account` | Operating bank asset |
   | `undeposited_funds` | Asset or clearing account |
   | `accounts_receivable` | Receivable asset |
   | `accounts_payable` | Payable liability |
   | `rental_income` | Revenue or income |
   | `repairs_and_maintenance_expense` | Expense |
   | `tenant_security_deposits_liability` | Liability |
   | `owner_contributions_equity` | Equity |
   | `owner_distributions_equity` | Equity |

   Enter the real account identifier/code, name, and accepted type. Mark required mappings required and enabled. Optional mappings are `credit_card_liability`, `mortgage_or_loan_liability`, `interest_expense`, and `principal_payment_mapping`. Enable them only when used and valid. A locally accepted mapping still needs confirmation against the actual LedgerOS account.

4. Run the setup smoke check after saving the settings:

   ```sh
   pl exec -T propertyledger-web python manage.py run_setup_smoke
   ```

   Expect **Setup smoke passed and was recorded.** This command checks the local database, LedgerOS health, and setup requirements. It saves the check result and marks setup complete when successful. A failed check can return a previously complete setup to in-progress. It does not post an accounting transaction or prove that the selected period is open and all mappings exist upstream.

5. Open PropertyLedger's root setup page `/` and **Home** at `/home/`. Confirm that the correct books appear and setup is complete. Have the bookkeeper verify the accounting selections before enabling financial work.

**Do not run `bootstrap_ledgeros_account_mappings` in production.** It writes hard-coded demo account IDs and overwrites existing mappings. The standard `make migrate` and `make smoke` targets invoke it. The development bootstrap and archived seed/reset scripts also have development side effects. Use the explicit production commands in this manual instead.

Connection settings are persisted in the PropertyLedger database. Changing the environment and restarting the container does not automatically replace the saved base URL or client ID. `bootstrap_ledgeros_connection_settings` overwrites that saved configuration from the environment; rerun it only for an intentional connection change, then review the result. Changing a secret value instead requires recreating the application container so the new environment is loaded.

## Users and access

Use the initial superuser for setup and recovery. Create named daily-use accounts and assign only the needed access. PropertyLedger accounts and LedgerOS accounts are separate; users do not automatically exist in both applications.

PropertyLedger's roles use these exact Django group names:

| Group | Normal responsibility |
| --- | --- |
| `PropertyLedger Admin` | Setup and application administration. |
| `PropertyLedger Property Manager` | Property, tenant, lease, and maintenance work. |
| `PropertyLedger Bookkeeper` | Accounting workflow entry and reporting. |
| `PropertyLedger Owner Viewer` | Read access to available owner/reporting views. |
| `PropertyLedger Read Only Viewer` | Read access to allowed reporting views. |

In `/admin/`, open **Users**, create the user, set a password, mark the account active, and assign the appropriate group. Group membership controls workflow access. Django's **Staff status** separately permits entry to the administration site; ordinary managers and bookkeepers can use the workflow screens without staff or superuser status. Avoid multiple role groups unless their combined access is intentional.

If the role groups are absent after migration, create the standard groups through the existing application helper:

```sh
pl exec -T propertyledger-web python manage.py shell -c 'from ledgeros.roles import ensure_role_groups; ensure_role_groups()'
```

Vendor bill approval and payment require separate **Workflow authorization** settings, including `can_approve_vendor_bills` and `can_pay_vendor_bills`. Role assignment alone does not express those business authorizations. Obtain the responsible manager's access decision and test it with the user's actual account.

Disable an account by clearing **Active** when access ends. Retain the user record so historical activity remains attributable. Do not grant superuser access to solve a missing workflow button.

## Release acceptance

Use a separate staging pair of databases and the same release images before deployment. Keep staging API credentials pointed at the staging LedgerOS endpoint. Never run automated tests, demo seeding, or simulated accounting postings against the live books.

Before opening production access, record:

- The two image digests/source commits, deployment date, administrator, database volume names, and backup location.
- Successful migrations and reviewed `check --deploy` output for both applications.
- Both DNS names resolve to the reserved LAN IP from employee workstations. HTTPS has no certificate warnings, HTTP redirects, login/form submission works, and static assets load.
- Only Caddy publishes host web ports. Application/database ports are unreachable from the LAN, and both sites are inaccessible from excluded networks. Verify any VPN exclusion explicitly.
- A full MacBook reboot recovers macOS access, Docker Desktop, Caddy, both applications, and the selected volumes; document any required FileVault unlock or user login.
- Certificate renewal and expiry alerts work for the selected method; DNS provider credentials or CA renewal ownership are recorded.
- Both application container health checks pass. PropertyLedger's current LedgerOS probe and setup smoke pass using the real HTTPS hostname. The proxy rejects its blocked unauthenticated health and sync-event paths.
- A successful setup smoke result and the bookkeeper's confirmation of entity, open period, and mapping values.
- A staging end-to-end accounting check covering tenant/customer provisioning, invoice posting, receipt posting, vendor/bill posting, and the approval/payment process used by the organization. Confirm the expected LedgerOS records and safe retry behavior. Health checks alone do not exercise authenticated write permissions.
- Working access for a manager, bookkeeper, and any assigned approver/payer, including denial of actions they should not perform.
- Daily encrypted PostgreSQL backups are copied off the MacBook, failures are reported, and paired restoration has been rehearsed. Record retention, recovery point/time, and protected recovery copies of Caddy state and credentials.

Current operational limits need an explicit release decision. Posted local payment deletion through admin is not fully protected, some admin/service payment paths lack the shared readiness gate, and non-Home connection indicators can show an older check. Until these are resolved, keep financial work in the supported workflow screens, restrict admin access, preserve posted records, and use current probes to diagnose connectivity. These gaps are tracked in [issue 30](https://github.com/timolingh/propertyledger/issues/30), [issue 31](https://github.com/timolingh/propertyledger/issues/31), and [issue 32](https://github.com/timolingh/propertyledger/issues/32).

## Routine operations

With `pl`, `lo`, and `caddy_stack` defined as above:

```sh
pl ps
lo ps
caddy_stack ps
caddy_stack logs --tail=100 caddy
pl logs --tail=100 propertyledger-web
lo logs --tail=100 web
pl logs --tail=100 propertyledger-db
lo logs --tail=100 db
```

Monitor HTTP availability, application errors, PostgreSQL health, disk space, certificate expiry, backup completion, and failed accounting syncs. Protect logs because they may contain personal or financial details. Configure log rotation in the container engine or centralized log collector so logs cannot fill the workstation disk.

The PropertyLedger container health check uses `/api/health/local/` for its own database. Caddy blocks the unauthenticated health paths from browser access. For a current backend check, use an administrative command inside the application container:

```sh
pl exec -T propertyledger-web python manage.py shell -c 'from ledgeros.services import LedgerOSHealthCheckService; result = LedgerOSHealthCheckService.check(); print(result); raise SystemExit(0 if result.healthy else 1)'
```

The LedgerOS health check requires credential values to be present locally, but the upstream health endpoint does not authenticate them. A healthy response therefore cannot validate the HMAC secret or accounting API permissions. A healthy container process, a health response, and a completed accounting transaction are different checks.

Use `restart` only to restart an unchanged container. To load edited environment values or a newly selected image, recreate the service:

```sh
pl up -d --force-recreate propertyledger-web
lo up -d --force-recreate web
```

For a Caddyfile change, validate and reload the running Caddy service:

```sh
caddy_stack exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
caddy_stack exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force
```

A replaced certificate needs a reload too. A changed DNS token or Caddy image requires container recreation with `caddy_stack up -d --force-recreate`. Preserve Caddy's data/config volumes. Keep macOS, Docker Desktop, dependencies, and approved images maintained; check resource usage and certificate/backup alerts. A health check marks a container unhealthy but does not itself guarantee restart or recovery.

Coordinate HMAC-secret rotation across both applications during a maintenance window. Update both protected environment files, recreate both application services, and verify health plus an authorized API workflow before restoring financial access. Do not print secrets into a ticket or log.

For application outages, retain the saved workflow records. Recover LedgerOS connectivity before retrying from the original record. A timeout can occur after LedgerOS accepted the transaction; creating a replacement record can create a different accounting request. Use the original idempotency history and LedgerOS evidence to determine the outcome.

## Backups and recovery

### Back up both databases

Back up the PropertyLedger database for operational records, users, mappings, workflow history, audit records, and sync identifiers. Back up LedgerOS separately for accounting records. Also retain all three Compose configurations, image digests, Caddyfile, Caddy data/config volumes, API client configuration, and securely stored credentials/certificate keys. Configure a daily backup job under the deployment user while Docker is running, with failure alerts and an encrypted off-host destination. `~/forte-server/backups` is temporary protected staging, not the backup destination.

For a coordinated maintenance backup, block employee access and stop Caddy and both application services. Ensure no other accounting client or job is writing to LedgerOS during the backup window. Keep the databases running:

```sh
cd "$forte_root"
caddy_stack stop caddy
pl stop propertyledger-web
lo stop web
umask 077
backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
pl exec -T propertyledger-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/propertyledger-$backup_stamp.dump"
lo exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/ledgeros-$backup_stamp.dump"
```

Check each command's exit status before continuing. Check that each archive is readable:

```sh
pl exec -T propertyledger-db pg_restore --list < "backups/propertyledger-$backup_stamp.dump"
lo exec -T db pg_restore --list < "backups/ledgeros-$backup_stamp.dump"
```

While Caddy is stopped, also archive its persistent state. These archives contain sensitive certificate material, including private CA keys when using the internal CA:

```sh
caddy_stack run --rm --no-deps -T --entrypoint tar caddy -C /data -czf - . > "backups/caddy-data-$backup_stamp.tgz"
caddy_stack run --rm --no-deps -T --entrypoint tar caddy -C /config -czf - . > "backups/caddy-config-$backup_stamp.tgz"
```

Check command success, encrypt the staged dumps/archives using Forte's approved backup system, copy them off-host, and verify the destination copy. Preserve matching configuration and image identifiers with the set. Apply the agreed retention policy after a successful transfer. For an upgrade, keep services stopped and continue with the migration procedure. For a backup without an upgrade, start LedgerOS, then PropertyLedger, then Caddy, verify health, and restore authorized employee access:

```sh
lo up -d web
pl up -d propertyledger-web
caddy_stack up -d
```

`pg_dump` produces a consistent backup of each individual database; separate running databases do not automatically produce a coordinated accounting recovery point. Routine online backups are useful, but a recovery plan must account for any transactions between their snapshot times. Copying live PostgreSQL volume files is not a substitute for a database-aware backup.

### Restore into an isolated environment

Rehearse recovery before launch and after material schema changes. Use separate recovery project names, new empty volumes, a separate shared proxy network, and isolated test DNS/proxy bindings. Do not attach restored services or production-hostname aliases to the live `forte` network. They must have no route or credentials that allow posting to production LedgerOS. Restore using the same application release and compatible PostgreSQL version first. Production credentials and URLs must not allow a restored PropertyLedger instance to post to live books.

With `pl`, `lo`, `caddy_stack`, and `forte_root` redefined to target the **isolated recovery installation**, change to that recovery directory and restore into fresh empty databases before running application migrations:

```sh
pl exec -T propertyledger-db sh -c 'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/PROPERTYLEDGER_BACKUP.dump
lo exec -T db sh -c 'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/LEDGEROS_BACKUP.dump
```

These commands assume empty destination databases. Do not restore over a running or populated production database. Use the paired backups, update the restored PropertyLedger connection settings to the isolated LedgerOS endpoint, and check record counts, key balances, posted transaction references, and sync status with the bookkeeper.

Restore Caddy state into fresh recovery volumes with its service stopped:

```sh
caddy_stack run --rm --no-deps -T --entrypoint tar caddy -C /data -xzf - < backups/CADDY_DATA_BACKUP.tgz
caddy_stack run --rm --no-deps -T --entrypoint tar caddy -C /config -xzf - < backups/CADDY_CONFIG_BACKUP.tgz
```

Restore its matching configuration and any company-issued certificate files before exposing HTTPS. Preserve the original internal CA when it is in use so employee and application trust remains valid; if its keys are lost, arrange CA replacement and redistribute trust before reopening service. Never distribute a private CA key to clients.

For a live disaster recovery, keep user access blocked while restoring the coordinated pair and validating it. If only one database can be restored, reconcile transactions and idempotency history across both applications before allowing writes. Never reset local sync status or delete LedgerOS entries to make the two systems appear aligned.

Do not use `docker compose down -v`, `make reset`, or volume pruning against the production projects. They can remove the persistent data this recovery process depends on.

## Upgrades and rollback

1. Test the matched release images, migrations, and accounting workflows in staging. Review changes to API contracts and determine whether each migration supports rollback.
2. Schedule a maintenance window, block employee access, and take the coordinated database/Caddy backups above. Keep Caddy and both application writers stopped for the migrations. Record the previous image digests and configuration.
3. Select and pull the new LedgerOS image with its collected static assets already included. Run migrations and deployment checks with `lo run --rm web ...` as in first deployment. Start LedgerOS and verify its health.
4. Select and pull the new PropertyLedger image with its collected static assets already included. Run migrations and deployment checks with `pl run --rm propertyledger-web ...`. Start PropertyLedger and verify its container health. Do not run the demo mapping bootstrap.
5. Start Caddy with employee access still blocked. Verify HTTPS login, the current LedgerOS connection, and saved setup. Recheck the real books and mappings when the release changes their requirements. Repeat relevant release acceptance checks, then reopen access. Retain the previous images and paired backups through the agreed rollback period.

A previous application image is safe to restart only when it is compatible with the migrated schema. If a schema change is incompatible, recover the coordinated databases and matching images from the maintenance backup. Restoring that backup discards later writes, so keep the maintenance barrier in place until the release decision is complete. Do not attempt reverse migrations without a tested procedure for that release.

## Troubleshooting

| Symptom | Check and corrective action |
| --- | --- |
| Site cannot be found | Check internal DNS against the reserved LAN address, Ethernet/DHCP reservation, permitted network ranges, Docker Desktop, and Caddy. Containers should resolve the production hostnames to Caddy on `forte`. |
| Caddy returns 502 or 504 | Check Gunicorn/container logs and health, the shared `forte` network, and the exact upstream aliases `propertyledger-web` and `ledgeros-web`. Do not publish application ports as a workaround. |
| HTTP 400 or `DisallowedHost` | Confirm that each site's `DJANGO_ALLOWED_HOSTS` contains its own exact hostname, without a scheme or path, and the proxy preserves `Host`. |
| Login form fails with CSRF error or redirect loop | Confirm the production settings module, HTTPS origin, forwarding-header handling, secure cookies, and proxy scheme. Clear stale site cookies only after fixing configuration. |
| Missing CSS or unstyled admin | Confirm WhiteNoise is installed in the selected image, its middleware follows SecurityMiddleware, and collected static assets are included in that image. Rebuild the release image when assets are missing. |
| TLS error from PropertyLedger to LedgerOS | Check the certificate hostname/chain/expiry, Caddy hostname alias, and PropertyLedger image trust store. A company or Caddy CA trusted only by browsers is insufficient. Retain certificate verification. |
| LedgerOS says unauthorized or forbidden | Check the saved client ID, secret environment-variable name and actual runtime value, clock synchronization, configured client scopes/event types, and preservation of signed paths/headers. Leave the API key blank for the supplied HMAC client. |
| Environment changed but connection is unchanged | Inspect the saved connection settings. Recreate the container for changed secrets; intentionally rebootstrap or edit saved connection values when changing the URL/client. |
| Setup remains incomplete | Check entity and period IDs/names, required and enabled optional mappings, current LedgerOS health, and the detailed `run_setup_smoke` result. Do not manually mark setup complete to bypass a failure. |
| Account or period error during posting | Have the bookkeeper confirm the actual LedgerOS account and open period. A successful health or smoke check cannot establish these accounting facts. |
| A user cannot approve or pay | Check group membership and the separate workflow authorization. Test using the user's own account. |
| Payment status is uncertain after an error | Keep the original record and its sync identifiers. Compare LedgerOS evidence and retry through the supported workflow after connectivity recovers. Do not create a replacement payment or edit posted fields directly. |
| Database appears empty after redeployment | Check the Compose project, volume attachment, database name, and selected environment before creating records. A different project can attach a new empty volume. |
| Certificate issuance or renewal fails | Check the selected CA method, real DNS provider plugin/token, outbound DNS/HTTPS access, or company certificate mount/renewal. Private LAN sites cannot rely on public inbound HTTP validation. |
| Browser trusts HTTPS but the application does not | Install the public CA chain in the PropertyLedger image and recreate its container. Do not export or distribute a CA private key. |
| Service remains down after reboot | Check FileVault unlock, the deployment user's login, Docker Desktop startup, host sleep, and all three Compose projects. A restart policy cannot start Docker Desktop itself. |
| Disk is filling | Check PostgreSQL data growth, container logs, image retention, and backup storage. Preserve named database volumes and required rollback artifacts. |

The [product specification](PropertyLedger_PRD_v1.0.md) describes desired functionality and current gaps. The [user manual](user-manual.md) describes the supported day-to-day workflows. Neither archived documentation nor demo configuration is required to operate this deployment.

## Local demonstration

From the PropertyLedger checkout, run:

```sh
./scripts/demo.sh
```

This single launcher builds both applications from the current source, recreates the isolated `propertyledger-demo` containers and database volumes, runs migrations, prompts you to create a LedgerOS superuser, and seeds seven walkthroughs. It uses the sibling `../ledgeros_v2` checkout by default; set `DEMO_LEDGEROS_REPO` to use another location. Docker must be running. The first build needs access to its base images and package repositories.

Open PropertyLedger at `http://localhost:8100/` and LedgerOS administration at `http://localhost:8101/admin/`. The launcher generates PropertyLedger credentials for `demo-admin`, `demo-manager`, and `demo-bookkeeper`, prints them, and saves them with scenario links in the private `.demo/summary.txt` file. The LedgerOS login is the one you create at its prompt. Environment files from either checkout are excluded from the demo images and configuration.

| Scenario | Starting point | Walkthrough |
| --- | --- | --- |
| M1 | Open faucet repair | Triage, assign, and start work. |
| M2 | Assigned hallway light repair | Start, verify, and close work. |
| M3 | Gate repair in progress | Verify and close with a vendor invoice pending. |
| I1 | Draft rent invoice for $1,500 | Review, post, and record a receipt. |
| I2 | Posted rent invoice for $1,250 | Review and record a receipt. |
| B1 | Approved and posted unpaid bill for $240 | Record full payment. |
| B2 | Approved and posted unpaid bill for $180 | Record a $90 partial payment. |

Use `demo-manager` for maintenance and approval, and `demo-bookkeeper` for invoicing, receipts, and payment. Accounting postings go to the demo LedgerOS database. Payment buttons record simulated payments; they do not move money.

**Every launch deletes the previous demo data from both demo databases.** The launcher fixes the Compose project name and uses separate databases and local loopback ports; it does not reset the development or production stacks. Set `DEMO_PROPERTYLEDGER_PORT` and `DEMO_LEDGEROS_PORT` if the default demo ports are occupied. The script's `--help` describes the optional automation mode.

To inspect or stop the demo without deleting its data, run these commands from the checkout:

```sh
docker compose -p propertyledger-demo --env-file .demo/demo.env -f .demo/compose.yml logs --tail=100
docker compose -p propertyledger-demo --env-file .demo/demo.env -f .demo/compose.yml stop
```

Use the launcher again to rebuild and restore the seven starting scenarios. The demo uses development servers and HTTP on the local workstation; use the production procedures above for the internal HTTPS deployment.
