.PHONY: help up down migrate smoke build test check shell dev-bootstrap

help:
	@printf '%s\n' \
		'PropertyLedger container workflow:' \
		'  make up           - start PropertyLedger only' \
		'  make down         - stop the PropertyLedger stack' \
		'  make reset        - stop the PropertyLedger stack and remove volumes' \
		'  make migrate      - run PropertyLedger migrations and local bootstrap commands' \
		'  make smoke        - verify PropertyLedger and the configured LedgerOS endpoint' \
		'  make dev-bootstrap - bootstrap LedgerOS-related setup rows without rewriting .env' \
		'  make test         - run the Django test suite in Docker only' \
		'  make check        - run Django checks in Docker only' \
		'  make shell        - open a Django shell in the PropertyLedger web container'

up:
	docker compose -f docker-compose.yml up -d --build

down:
	docker compose -f docker-compose.yml down --remove-orphans

reset:
	docker compose -f docker-compose.yml down -v --remove-orphans

build:
	docker compose -f docker-compose.yml build

test:
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py test

check:
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py check
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py makemigrations --check --dry-run

shell:
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py shell

migrate:
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py migrate
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings
	docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_payment_workflow_settings

smoke:
	docker compose -f docker-compose.yml up -d --build
	docker compose -f docker-compose.yml exec -T propertyledger-web python manage.py migrate
	docker compose -f docker-compose.yml exec -T propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
	docker compose -f docker-compose.yml exec -T propertyledger-web python manage.py bootstrap_ledgeros_account_mappings
	docker compose -f docker-compose.yml exec -T propertyledger-web python manage.py bootstrap_payment_workflow_settings
	docker compose -f docker-compose.yml exec -T propertyledger-web python manage.py shell -c "from django.test import Client; from django.db import connection; from ledgeros.services import LedgerOSHealthCheckService; response = Client(HTTP_HOST='localhost').get('/api/health/local/'); payload = response.json(); assert response.status_code == 200, response.content; assert payload['healthy']; cursor = connection.cursor(); cursor.execute('SELECT 1'); assert cursor.fetchone()[0] == 1; cursor.close(); ledgeros = LedgerOSHealthCheckService.check(); assert ledgeros.healthy is True, ledgeros.details"

dev-bootstrap:
	./scripts/dev-bootstrap.sh
