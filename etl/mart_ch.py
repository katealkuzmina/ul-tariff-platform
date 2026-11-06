"""Репликация mart.route_card в ClickHouse (бонус-задача).

Идемпотентно: полная перезапись партиций через TRUNCATE + батчевый insert
(clickhouse-connect client.insert). Включается env-флагом REPLICATE_TO_CH=1
после пересчёта витрины в PostgreSQL.
"""

import logging
import os

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

log = logging.getLogger(__name__)

COLUMNS = [
    "month_date", "loading_gc_id", "unloading_gc_id", "loading_city", "unloading_city",
    "body_group", "weight_category", "p25_trip", "median_trip", "p75_trip", "avg_trip",
    "p25_km", "median_km", "p75_km", "trips_count", "carriers_count", "cv_rate",
    "mom_pct", "yoy_pct", "reliability_level",
]


def _ch_client():
    import clickhouse_connect

    host = os.environ.get("CLICKHOUSE_HOST", "clickhouse")
    port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
    return clickhouse_connect.get_client(host=host, port=port, database="mart")


def replicate_route_card(conn: Connection) -> int:
    df = pd.read_sql(
        text(f'SELECT {", ".join(COLUMNS)} FROM mart.route_card'), conn
    )
    if conn.in_transaction():
        conn.commit()
    if df.empty:
        return 0
    df["month_date"] = pd.to_datetime(df["month_date"]).dt.date
    client = _ch_client()
    client.command("TRUNCATE TABLE mart.route_card")
    client.insert("mart.route_card", df[COLUMNS].values.tolist(), column_names=COLUMNS)
    log.info("mart.route_card replicated to ClickHouse: %d rows", len(df))
    return len(df)
