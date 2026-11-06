#!/bin/bash
# Инициализация Superset: мета-БД в PostgreSQL, admin, подключение к DWH,
# примерные датасеты витрин (plan Task 12).
set -e

PG_USER="${POSTGRES_USER:-postgres}"
PG_PASSWORD="${POSTGRES_PASSWORD:-postgres}"

superset db upgrade

superset fab create-admin \
  --username "${SUPERSET_ADMIN_USER:-admin}" \
  --password "${SUPERSET_ADMIN_PASSWORD:-admin}" \
  --firstname Admin --lastname Admin \
  --email admin@example.com 2>/dev/null || true

superset init

superset set-database-uri \
  --database-name "deals_bigdata" \
  --uri "postgresql+psycopg2://${PG_USER}:${PG_PASSWORD}@db:5432/deals_bigdata" 2>/dev/null || true

python - << 'PY'
from superset.app import create_app

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    database = db.session.query(Database).filter_by(database_name="deals_bigdata").one()
    for schema, table in [("mart", "route_card"), ("mart", "ml_price_predictions")]:
        exists = (
            db.session.query(SqlaTable)
            .filter_by(database_id=database.id, schema=schema, table_name=table)
            .first()
        )
        if not exists:
            db.session.add(SqlaTable(database_id=database.id, schema=schema, table_name=table))
    db.session.commit()
    print("datasets:", [t.table_name for t in db.session.query(SqlaTable).all()])
PY

echo "Superset initialized: http://localhost:8088 (login ${SUPERSET_ADMIN_USER:-admin}/${SUPERSET_ADMIN_PASSWORD:-admin})"

superset run -h 0.0.0.0 -p 8088 --with-threads --reload --debugger
