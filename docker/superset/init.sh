#!/bin/bash
# Инициализация Superset: мета-БД в PostgreSQL, admin, подключение к DWH.
set -e

superset db upgrade

superset fab create-admin \
  --username "${SUPERSET_ADMIN_USER:-admin}" \
  --password "${SUPERSET_ADMIN_PASSWORD:-admin}" \
  --firstname Admin --lastname Admin \
  --email admin@example.com 2>/dev/null || true

superset init

superset set-database-uri \
  --database-name "deals_bigdata" \
  --uri "postgresql+psycopg2://postgres:postgres@db:5432/deals_bigdata" 2>/dev/null || true

echo "Superset initialized: http://localhost:8088 (login ${SUPERSET_ADMIN_USER:-admin}/${SUPERSET_ADMIN_PASSWORD:-admin})"

superset run -h 0.0.0.0 -p 8088 --with-threads --reload --debugger
