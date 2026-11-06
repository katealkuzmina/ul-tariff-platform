"""Загрузка очищенного слоя core из raw: валидация, валюты, категории, карантин.

Идемпотентность окна: DELETE строк окна + вставка в одной транзакции.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.extract import _copy_frame
from etl.transform import add_categories, validate_frame

log = logging.getLogger(__name__)

CORE_COLUMNS = [
    "price_id",
    "loading_date",
    "loading_city_gcid",
    "unloading_city_gcid",
    "distance",
    "total_weight",
    "total_volume",
    "body_type",
    "price",
    "currency_code",
    "price_rub",
    "complex",
    "price_type",
    "is_fact",
    "organization_id",
    "outlier_mark",
    "weight_category",
    "volume_category",
]


@dataclass(frozen=True)
class CoreReport:
    loaded: int
    quarantined: int
    by_reason: dict = field(default_factory=dict)


def _fetch_ref_data(conn: Connection):
    city_gc_ids = set(conn.execute(text("SELECT gc_id FROM public.cities")).scalars())
    rates = pd.read_sql(
        text("SELECT num_code, setting_date, value FROM public.exchange_rates"), conn
    )
    fx_dates = set(zip(rates["num_code"], rates["setting_date"]))
    rates_idx = {
        (r.num_code, r.setting_date): r.value for r in rates.itertuples(index=False)
    }
    return city_gc_ids, rates_idx, fx_dates


def _compute_price_rub(df: pd.DataFrame, rates_idx: dict) -> pd.Series:
    """RUB — курс 1.0; валюта — точный курс на nearest_rate_date (внешний join)."""
    values = []
    for price, cur, nrd in zip(df["price"], df["currency_code"], df["nearest_rate_date"]):
        if cur == "643":
            raw_value = float(price)
        else:
            rate = rates_idx.get((cur, nrd))
            raw_value = float(price) * float(rate) if rate is not None else None
        if raw_value is None:
            values.append(None)
        else:
            values.append(Decimal(str(raw_value)).quantize(Decimal("0.01"), ROUND_HALF_UP))
    return pd.Series(values, index=df.index)


def _clean_payload(row: pd.Series) -> str:
    payload = {}
    for key, value in row.items():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            payload[key] = None
        else:
            payload[key] = value
    return json.dumps(payload, default=str, ensure_ascii=False)


def build_core(conn: Connection, start_date: date, end_date: date) -> CoreReport:
    if conn.in_transaction():
        conn.commit()
    params = {"s": start_date, "e": end_date}
    raw = pd.read_sql(
        text("SELECT * FROM raw.prices WHERE loading_date BETWEEN :s AND :e"), conn, params=params
    )
    if conn.in_transaction():
        conn.commit()

    city_gc_ids, rates_idx, fx_dates = _fetch_ref_data(conn)
    if conn.in_transaction():
        conn.commit()

    raw = raw.rename(columns={"id": "price_id"})
    if raw.empty:
        with conn.begin():
            conn.execute(
                text("DELETE FROM core.prices_clean WHERE loading_date BETWEEN :s AND :e"), params
            )
            conn.execute(
                text("DELETE FROM core.dq_quarantine_prices WHERE loading_date BETWEEN :s AND :e"),
                params,
            )
        return CoreReport(loaded=0, quarantined=0, by_reason={})

    df = add_categories(raw)
    df["price_rub"] = _compute_price_rub(df, rates_idx)
    df["reason"] = validate_frame(df, city_gc_ids, fx_dates)

    valid = df[df["reason"].isna()]
    quarantined = df[df["reason"].notna()]

    with conn.begin():
        conn.execute(
            text("DELETE FROM core.prices_clean WHERE loading_date BETWEEN :s AND :e"), params
        )
        conn.execute(
            text("DELETE FROM core.dq_quarantine_prices WHERE loading_date BETWEEN :s AND :e"),
            params,
        )
        _copy_frame(conn, valid[CORE_COLUMNS], "core.prices_clean")
        if not quarantined.empty:
            qua = pd.DataFrame(
                {
                    "price_id": quarantined["price_id"],
                    "loading_date": quarantined["loading_date"],
                    "reason_code": quarantined["reason"],
                    "payload": [_clean_payload(r) for _, r in quarantined.iterrows()],
                }
            )
            _copy_frame(conn, qua, "core.dq_quarantine_prices")

    by_reason = quarantined["reason"].value_counts().to_dict() if not quarantined.empty else {}
    log.info(
        "core load window=%s..%s read=%d loaded=%d quarantined=%d by_reason=%s",
        start_date,
        end_date,
        len(raw),
        len(valid),
        len(quarantined),
        by_reason,
    )
    return CoreReport(loaded=len(valid), quarantined=len(quarantined), by_reason=by_reason)


def refresh_dim_cities(conn: Connection) -> int:
    with conn.begin():
        conn.execute(text("DELETE FROM core.dim_cities"))
        result = conn.execute(
            text(
                """
                INSERT INTO core.dim_cities (gc_id, city_id, city_name, region, latitude, longitude)
                SELECT DISTINCT ON (gc_id)
                    gc_id, id, name,
                    NULLIF(trim(split_part(full_name_local, ',', 2)), ''),
                    latitude, longitude
                FROM public.cities
                ORDER BY gc_id, id
                """
            )
        )
        rowcount = result.rowcount
    log.info("dim_cities refreshed: %d rows", rowcount)
    return rowcount


def refresh_body_groups(conn: Connection) -> int:
    with conn.begin():
        conn.execute(text("DELETE FROM core.price_body_groups"))
        result = conn.execute(
            text(
                """
                INSERT INTO core.price_body_groups (price_id, body_group)
                SELECT DISTINCT p.id,
                    CASE COALESCE(bt.std_id, fb.std_id)
                        WHEN 56 THEN 'Тент'
                        WHEN 4  THEN 'Рефрижератор'
                        WHEN 2  THEN 'Изотерм'
                        WHEN 15 THEN 'Борт'
                        WHEN NULL THEN 'Не указан'
                        ELSE 'Прочие'
                    END
                FROM public.prices p
                LEFT JOIN public.price_body_types pbt ON pbt.price_id = p.id
                LEFT JOIN public.body_types bt ON bt.id = pbt.body_type_id
                LEFT JOIN public.body_types fb ON fb.id = p.body_type
                """
            )
        )
        rowcount = result.rowcount
    log.info("price_body_groups refreshed: %d rows", rowcount)
    return rowcount
