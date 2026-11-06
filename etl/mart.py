"""Пересчёт аналитических витрин слоя mart (полный рефреш в транзакции)."""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.config import SQL_DIR

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MartReport:
    rows: int
    max_month: date | None


def _read_sql(name: str) -> str:
    return (SQL_DIR / "mart" / name).read_text(encoding="utf-8")


def build_route_card(conn: Connection, as_of: date) -> MartReport:
    """Полный идемпотентный пересчёт mart.route_card за всю историю core."""
    if conn.in_transaction():
        conn.commit()
    with conn.begin():
        conn.execute(text("TRUNCATE mart.route_card"))
        result = conn.execute(text(_read_sql("mart_route_card.sql")), {"as_of": as_of})
        rows = result.rowcount
    max_month = conn.execute(text("SELECT max(month_date) FROM mart.route_card")).scalar()
    if conn.in_transaction():
        conn.commit()
    log.info("mart.route_card rebuilt: rows=%d max_month=%s", rows, max_month)
    return MartReport(rows=rows, max_month=max_month)
