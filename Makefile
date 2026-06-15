.PHONY: help up down build test shell

help:
	@printf '%s\n' \
		'PropertyLedger container workflow:' \
		'  make up     - start the local Docker Compose stack' \
		'  make down   - stop the local Docker Compose stack' \
		'  make build  - build the Docker images' \
		'  make test   - run the Django test suite in Docker only' \
		'  make shell  - open a Django shell in the web container'

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

test:
	docker compose run --rm web python manage.py test

shell:
	docker compose run --rm web python manage.py shell
