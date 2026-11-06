"""Batch-скоринг: прогнозы для тестового окна и плановых будущих заявок.

Для сделки с несколькими группами кузова скоринг ведётся на канонической
(минимальной по алфавиту) группе — детерминированный выбор одной строки
на price_id. Для будущих заявок факт и ошибки NULL, даже если цена известна.
Идемпотентность: DELETE по model_name + INSERT в одной транзакции.
"""

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ml.dataset import split_bounds
from ml.features import FEATURE_COLUMNS, add_cyclical
from ml.train import ARTIFACTS_DIR

log = logging.getLogger(__name__)

SCORING_SQL = """
SELECT p.price_id,
       p.loading_date,
       p.loading_city_gcid,
       p.unloading_city_gcid,
       p.price_rub,
       cl.city_name  AS origin_city,
       cl.region     AS origin_region,
       cl.latitude   AS origin_latitude,
       cl.longitude  AS origin_longitude,
       cu.city_name  AS destination_city,
       cu.region     AS destination_region,
       cu.latitude   AS destination_latitude,
       cu.longitude  AS destination_longitude,
       p.distance,
       p.total_weight,
       p.total_volume,
       p.weight_category,
       p.volume_category,
       (SELECT min(g.body_group)
          FROM core.price_body_groups g
         WHERE g.price_id = p.price_id) AS body_group
FROM core.prices_clean p
JOIN core.dim_cities cl ON cl.gc_id = p.loading_city_gcid
JOIN core.dim_cities cu ON cu.gc_id = p.unloading_city_gcid
WHERE (p.is_fact AND NOT p.complex AND p.price_rub IS NOT NULL
       AND p.loading_date BETWEEN :test_start AND :as_of)
   OR (p.loading_date > :as_of)
"""


def _load_model(model_name: str) -> CatBoostRegressor:
    path = ARTIFACTS_DIR / f"{model_name}.cbm"
    if not path.exists():
        raise FileNotFoundError(
            f"model artifact not found: {path}. Run ml.train.run_training first."
        )
    model = CatBoostRegressor()
    model.load_model(str(path))
    return model


def run_scoring(conn: Connection, model_name: str, as_of: date) -> int:
    if conn.in_transaction():
        conn.commit()
    _, test_start, _ = split_bounds(as_of)
    df = pd.read_sql(
        text(SCORING_SQL), conn, params={"test_start": test_start, "as_of": as_of}
    )
    if conn.in_transaction():
        conn.commit()
    if df.empty:
        with conn.begin():
            conn.execute(
                text("DELETE FROM mart.ml_price_predictions WHERE model_name = :m"),
                {"m": model_name},
            )
        return 0

    df["loading_date"] = pd.to_datetime(df["loading_date"])
    df = add_cyclical(df)
    df = df[df["body_group"].notna()].reset_index(drop=True)

    model = _load_model(model_name)
    X = df[FEATURE_COLUMNS].copy()
    df["predicted_price_rub"] = np.maximum(model.predict(X), 0.0)

    is_history = df["loading_date"] <= pd.Timestamp(as_of)
    actual = pd.to_numeric(df["price_rub"], errors="coerce").astype(float)
    predicted = df["predicted_price_rub"].astype(float)
    abs_error = (predicted - actual).abs()
    ape = np.where(actual > 0, abs_error / actual * 100.0, np.nan)

    out = pd.DataFrame(
        {
            "price_id": df["price_id"],
            "loading_date": df["loading_date"].dt.date,
            "loading_city_gcid": df["loading_city_gcid"],
            "unloading_city_gcid": df["unloading_city_gcid"],
            "body_group": df["body_group"],
            "actual_price_rub": np.where(is_history, actual, np.nan),
            "predicted_price_rub": predicted,
            "abs_error_rub": np.where(is_history, abs_error, np.nan),
            "ape_pct": np.where(is_history, ape, np.nan),
            "model_name": model_name,
        }
    )

    with conn.begin():
        conn.execute(
            text("DELETE FROM mart.ml_price_predictions WHERE model_name = :m"),
            {"m": model_name},
        )
        insert_sql = text(
            """
            INSERT INTO mart.ml_price_predictions (
                price_id, loading_date, loading_city_gcid, unloading_city_gcid,
                body_group, actual_price_rub, predicted_price_rub,
                abs_error_rub, ape_pct, model_name, scored_at
            )
            VALUES (
                :price_id, :loading_date, :loading_city_gcid, :unloading_city_gcid,
                :body_group, :actual_price_rub, :predicted_price_rub,
                :abs_error_rub, :ape_pct, :model_name, now()
            )
            """
        )
        conn.execute(
            insert_sql,
            [
                {
                    "price_id": int(r.price_id),
                    "loading_date": r.loading_date,
                    "loading_city_gcid": int(r.loading_city_gcid),
                    "unloading_city_gcid": int(r.unloading_city_gcid),
                    "body_group": r.body_group,
                    "actual_price_rub": None if pd.isna(r.actual_price_rub) else float(r.actual_price_rub),
                    "predicted_price_rub": float(r.predicted_price_rub),
                    "abs_error_rub": None if pd.isna(r.abs_error_rub) else float(r.abs_error_rub),
                    "ape_pct": None if pd.isna(r.ape_pct) else float(r.ape_pct),
                    "model_name": r.model_name,
                }
                for r in out.itertuples(index=False)
            ],
        )
    log.info(
        "scoring done: model=%s rows=%d (history=%d, future=%d)",
        model_name,
        len(out),
        int(is_history.sum()),
        int((~is_history).sum()),
    )
    return len(out)
