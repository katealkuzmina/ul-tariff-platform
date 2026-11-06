"""Извлечение сырых данных источника за окно дат в слой raw (идемпотентно).

Стратегия идемпотентности: DELETE строк окна + батчевая вставка выборки
в одной транзакции. Вставка — через COPY (psycopg3), без построчных INSERT.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class ExtractReport:
    read_rows: int
    read_price_dates: int


_INTEGER_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "smallserial",
    "serial",
    "bigserial",
}


def _align_dtypes(conn: Connection, df: pd.DataFrame, table: str) -> pd.DataFrame:
    schema, name = table.split(".")
    rows = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :name"
        ),
        {"schema": schema, "name": name},
    ).all()
    pg_types = {r[0]: r[1] for r in rows}
    out = df.copy()
    for col in out.columns:
        if pg_types.get(col) in _INTEGER_TYPES:
            out[col] = out[col].astype("Int64")
    return out


def _copy_frame(conn: Connection, df: pd.DataFrame, table: str) -> None:
    if df.empty:
        return
    df = _align_dtypes(conn, df, table)
    cols = list(df.columns)
    sql = f'COPY {table} ({", ".join(cols)}) FROM STDIN'
    raw_conn = conn.connection.driver_connection  # psycopg3 connection
    with raw_conn.cursor() as cur:
        with cur.copy(sql) as copy:
            for row in df.itertuples(index=False, name=None):
                copy.write_row(tuple(None if pd.isna(v) else v for v in row))


def load_raw_window(conn: Connection, start_date: date, end_date: date) -> ExtractReport:
    if conn.in_transaction():
        conn.commit()
    params = {"s": start_date, "e": end_date}

    prices = pd.read_sql(
        text("SELECT * FROM public.prices WHERE loading_date BETWEEN :s AND :e ORDER BY id"),
        conn,
        params=params,
    )
    price_dates = pd.read_sql(
        text(
            "SELECT pd.* FROM public.price_dates pd "
            "JOIN public.prices p ON p.id = pd.price_id "
            "WHERE p.loading_date BETWEEN :s AND :e ORDER BY pd.id"
        ),
        conn,
        params=params,
    )
    if conn.in_transaction():
        conn.commit()

    with conn.begin():
        conn.execute(
            text(
                "DELETE FROM raw.price_dates WHERE price_id IN "
                "(SELECT id FROM raw.prices WHERE loading_date BETWEEN :s AND :e)"
            ),
            params,
        )
        conn.execute(text("DELETE FROM raw.prices WHERE loading_date BETWEEN :s AND :e"), params)
        _copy_frame(conn, prices, "raw.prices")
        _copy_frame(conn, price_dates, "raw.price_dates")

    return ExtractReport(read_rows=len(prices), read_price_dates=len(price_dates))
