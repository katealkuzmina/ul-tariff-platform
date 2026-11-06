#!/bin/bash
set -e
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /opt/sql/schema.sql
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v n_prices="${N_PRICES:-300000}" -f /opt/sql/synthetic.sql
