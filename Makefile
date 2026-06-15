.PHONY: help up up-full down down-full migrate migrate-full smoke smoke-full build test check shell

BASE_COMPOSE = docker compose -f docker-compose.yml
FULLSTACK_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.ledgeros.yml

help:
	@printf '%s\n' \
		'PropertyLedger container workflow:' \
		'  make up-full    - start PropertyLedger plus real LedgerOS' \
		'  make down-full  - stop the PropertyLedger + LedgerOS stack' \
		'  make migrate-full - run migrations for PropertyLedger and LedgerOS' \
		'  make smoke-full - verify the full-stack health checks' \
		'  make test       - run the Django test suite in Docker only' \
		'  make check      - run Django checks in Docker only' \
		'  make shell      - open a Django shell in the PropertyLedger web container'

up: up-full

up-full:
	$(FULLSTACK_COMPOSE) up -d --build

down: down-full

down-full:
	$(FULLSTACK_COMPOSE) down --remove-orphans

build:
	$(BASE_COMPOSE) build

test:
	LEDGEROS_BASE_URL= LEDGEROS_CLIENT_ID= LEDGEROS_HMAC_SECRET= $(BASE_COMPOSE) run --rm propertyledger-web python manage.py test

check:
	LEDGEROS_BASE_URL= LEDGEROS_CLIENT_ID= LEDGEROS_HMAC_SECRET= $(BASE_COMPOSE) run --rm propertyledger-web python manage.py check
	LEDGEROS_BASE_URL= LEDGEROS_CLIENT_ID= LEDGEROS_HMAC_SECRET= $(BASE_COMPOSE) run --rm propertyledger-web python manage.py makemigrations --check --dry-run

shell:
	$(BASE_COMPOSE) run --rm propertyledger-web python manage.py shell

migrate: migrate-full

migrate-full:
	$(FULLSTACK_COMPOSE) run --rm ledgeros-web python manage.py migrate
	$(FULLSTACK_COMPOSE) run --rm propertyledger-web python manage.py migrate

smoke: smoke-full

smoke-full:
	$(FULLSTACK_COMPOSE) up -d --build
	$(FULLSTACK_COMPOSE) exec -T propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
	$(FULLSTACK_COMPOSE) exec -T propertyledger-web python manage.py shell -c "import json; import urllib.request; from django.db import connection; from ledgeros.services import LedgerOSHealthCheckService; response = urllib.request.urlopen('http://localhost:8000/api/health/local/'); payload = json.loads(response.read().decode('utf-8')); assert response.status == 200, response.read(); assert payload['healthy']; cursor = connection.cursor(); cursor.execute('SELECT 1'); assert cursor.fetchone()[0] == 1; cursor.close(); ledgeros = LedgerOSHealthCheckService.check(); assert ledgeros.healthy is True, ledgeros.details"
