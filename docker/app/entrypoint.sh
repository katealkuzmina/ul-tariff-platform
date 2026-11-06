#!/bin/bash
set -euo pipefail

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q; do
  echo "waiting for postgres at ${DB_HOST}:${DB_PORT}..."
  sleep 2
done

exec uv run python -m etl.runner "$@"
