"""ML-признаки: география, параметры груза/транспорта, циклическое кодирование дат.

Защита от утечек: в признаковое пространство не попадают таргет, сырьевые
пересчёты тарифа, служебные идентификаторы и агрегаты price_group_stats
(см. FORBIDDEN). Маршрут кодируется раздельно (отправление/назначение),
никаких склеенных строк маршрута высокой кардинальности.
"""

from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

TARGET = "price_rub"

FORBIDDEN = {
    "price",
    "price_with_vat",
    "price_rub",
    "price_km",
    "price_per_weight",
    "organization_id",
    "price_group_id",
    "avg_price",
    "min_km_price",
    "max_km_price",
    "outlier_mark",
    "nearest_rate_date",
    "subscriber_id",
}

CATEGORICAL_COLUMNS = [
    "origin_region",
    "destination_region",
    "origin_city",
    "destination_city",
    "body_group",
    "weight_category",
    "volume_category",
]

NUMERIC_COLUMNS = [
    "distance",
    "total_weight",
    "total_volume",
    "origin_latitude",
    "origin_longitude",
    "destination_latitude",
    "destination_longitude",
    "year",
    "month",
    "dayofweek",
    "dayofyear",
    "month_sin",
    "month_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
]

FEATURE_COLUMNS = CATEGORICAL_COLUMNS + NUMERIC_COLUMNS

DATASET_SQL = """
SELECT p.price_id,
       p.loading_date,
       p.distance,
       p.total_weight,
       p.total_volume,
       p.weight_category,
       p.volume_category,
       p.outlier_mark,
       p.price_rub,
       cl.city_name  AS origin_city,
       cl.region     AS origin_region,
       cl.latitude   AS origin_latitude,
       cl.longitude  AS origin_longitude,
       cu.city_name  AS destination_city,
       cu.region     AS destination_region,
       cu.latitude   AS destination_latitude,
       cu.longitude  AS destination_longitude,
       (SELECT min(g.body_group)
          FROM core.price_body_groups g
         WHERE g.price_id = p.price_id) AS body_group
FROM core.prices_clean p
JOIN core.dim_cities cl ON cl.gc_id = p.loading_city_gcid
JOIN core.dim_cities cu ON cu.gc_id = p.unloading_city_gcid
WHERE p.is_fact AND NOT p.complex AND p.price_rub IS NOT NULL
"""


def parse_region(full_name_local: str) -> tuple[str, Optional[str]]:
    """'Город, Регион' -> (город, регион); без запятой регион = None."""
    parts = full_name_local.split(",", 1)
    city = parts[0].strip()
    region = parts[1].strip() if len(parts) > 1 else None
    return city, region


def add_cyclical(df: pd.DataFrame) -> pd.DataFrame:
    """Годовой тренд (year) + гармонические признаки месяца/дня недели/дня года."""
    out = df.copy()
    dates = pd.to_datetime(out["loading_date"])
    out["year"] = dates.dt.year.astype("int64")
    out["month"] = dates.dt.month.astype("int64")
    out["dayofweek"] = dates.dt.day_of_week.astype("int64")
    out["dayofyear"] = dates.dt.day_of_year.astype("int64")
    out["month_sin"] = np.sin(2 * np.pi * out["month"] / 12)
    out["month_cos"] = np.cos(2 * np.pi * out["month"] / 12)
    out["dow_sin"] = np.sin(2 * np.pi * out["dayofweek"] / 7)
    out["dow_cos"] = np.cos(2 * np.pi * out["dayofweek"] / 7)
    out["doy_sin"] = np.sin(2 * np.pi * out["dayofyear"] / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * out["dayofyear"] / 365.25)
    return out


def load_dataset(conn: Connection) -> pd.DataFrame:
    """Фактические прямые перевозки с валидным таргетом, обогащённые гео-признаками."""
    df = pd.read_sql(text(DATASET_SQL), conn)
    if conn.in_transaction():
        conn.commit()
    df["loading_date"] = pd.to_datetime(df["loading_date"])
    return add_cyclical(df)


def build_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    X = df[FEATURE_COLUMNS].copy()
    y = df[TARGET].astype(float)
    meta = df[["price_id", "loading_date", "outlier_mark"]].copy()
    leakage = FORBIDDEN & set(X.columns)
    if leakage:
        raise ValueError(f"leakage columns in features: {sorted(leakage)}")
    return X, y, meta
