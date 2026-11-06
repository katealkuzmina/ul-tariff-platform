.PHONY: up down psql build test etl app

up:
	docker compose up -d db

down:
	docker compose down

build:
	docker compose build app

psql:
	docker compose exec db psql -U postgres -d deals_bigdata

test:
	docker compose run --rm app pytest -q

etl:
	docker compose run --rm app python -m etl.pipeline

app:
	docker compose up --build app
