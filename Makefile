.PHONY: up down build psql test etl-full mart ml app logs

up:
	docker compose up -d db

down:
	docker compose down

build:
	docker compose build app

logs:
	docker compose logs -f app

psql:
	docker compose exec db psql -U postgres -d deals_bigdata

# полный пайплайн (миграции -> ETL за весь период -> витрины -> ML -> скоринг)
app:
	docker compose up --build app

# бэкфилл за выбранное окно дат (идемпотентно)
etl:
	docker compose run --rm app etl --start $(START) --end $(END)

mart:
	docker compose run --rm app mart

ml:
	docker compose run --rm app ml

test:
	docker compose run --rm --entrypoint "uv run" app pytest -q
