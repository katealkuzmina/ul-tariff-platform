#!/bin/bash
# Дополнительные БД для бонус-сервисов (Airflow metadata, Superset metadata).
set -e
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 << 'SQL'
CREATE DATABASE airflow;
CREATE DATABASE superset;
SQL
