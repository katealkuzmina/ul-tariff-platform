"""Обучение моделей: CatBoost (основная) и Ridge (линейный бейзлайн).

Воспроизводимость: random_seed фиксирован, границы сплита детерминированы,
препроцессинг Ridge (imputer/scaler/one-hot) обучается строго на train.
Результаты пишутся в mart.model_metrics (идемпотентно по model_name).
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.config import Settings
from ml.dataset import time_split
from ml.evaluate import metrics
from ml.features import (
    CATEGORICAL_COLUMNS,
    NUMERIC_COLUMNS,
    build_xy,
    load_dataset,
)

log = logging.getLogger(__name__)

CAT_FEATURES = list(CATEGORICAL_COLUMNS)
CATBOOST_MODEL_NAME = "catboost_v1"
RIDGE_MODEL_NAME = "ridge_v1"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


@dataclass(frozen=True)
class ModelResult:
    model_name: str
    train_rows: int
    test_rows: int
    metrics: dict
    params: dict
    artifact_path: str | None = None


def train_catboost(X_train: pd.DataFrame, y_train, seed: int) -> CatBoostRegressor:
    model = CatBoostRegressor(
        loss_function="RMSE",
        random_seed=seed,
        cat_features=CAT_FEATURES,
        verbose=0,
        allow_writing_files=False,
    )
    model.fit(X_train, y_train)
    return model


def train_ridge(X_train: pd.DataFrame, y_train) -> Pipeline:
    prep = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline([("imputer", SimpleImputer()), ("scaler", StandardScaler())]),
                NUMERIC_COLUMNS,
            ),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLUMNS),
        ]
    )
    pipe = Pipeline([("prep", prep), ("model", Ridge())])
    pipe.fit(X_train, y_train)
    return pipe


def _write_metrics(conn: Connection, results: list[ModelResult]) -> None:
    names = [r.model_name for r in results]
    with conn.begin():
        conn.execute(
            text("DELETE FROM mart.model_metrics WHERE model_name = ANY(:names)"),
            {"names": names},
        )
        for r in results:
            conn.execute(
                text(
                    """
                    INSERT INTO mart.model_metrics
                        (model_name, train_rows, test_rows, r2, mape_pct, rmse_rub, mae_rub, params)
                    VALUES
                        (:model_name, :train_rows, :test_rows, :r2, :mape_pct, :rmse_rub, :mae_rub,
                         CAST(:params AS jsonb))
                    """
                ),
                {
                    "model_name": r.model_name,
                    "train_rows": r.train_rows,
                    "test_rows": r.test_rows,
                    "r2": r.metrics["r2"],
                    "mape_pct": r.metrics["mape_pct"],
                    "rmse_rub": r.metrics["rmse_rub"],
                    "mae_rub": r.metrics["mae_rub"],
                    "params": json.dumps(r.params, ensure_ascii=False),
                },
            )


def run_training(conn: Connection, settings: Settings) -> list[ModelResult]:
    if conn.in_transaction():
        conn.commit()
    df = load_dataset(conn)
    train_df, test_df = time_split(df, settings.as_of)
    X_train, y_train, _ = build_xy(train_df)
    X_test, y_test, _ = build_xy(test_df)
    log.info("training split: train=%d test=%d", len(X_train), len(X_test))

    catboost = train_catboost(X_train, y_train, seed=settings.seed)
    cb_pred = catboost.predict(X_test)
    cb_metrics = metrics(y_test, cb_pred)

    ridge = train_ridge(X_train, y_train)
    ridge_pred = ridge.predict(X_test)
    ridge_metrics = metrics(y_test, ridge_pred)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS_DIR / f"{CATBOOST_MODEL_NAME}.cbm"
    catboost.save_model(str(artifact_path))

    results = [
        ModelResult(
            model_name=CATBOOST_MODEL_NAME,
            train_rows=len(X_train),
            test_rows=len(X_test),
            metrics=cb_metrics,
            params={
                "seed": settings.seed,
                "loss_function": "RMSE",
                "cat_features": CAT_FEATURES,
                "algorithm": "CatBoostRegressor",
            },
            artifact_path=str(artifact_path),
        ),
        ModelResult(
            model_name=RIDGE_MODEL_NAME,
            train_rows=len(X_train),
            test_rows=len(X_test),
            metrics=ridge_metrics,
            params={"algorithm": "Ridge", "preprocessing": "SimpleImputer+StandardScaler+OneHot"},
        ),
    ]
    _write_metrics(conn, results)
    for r in results:
        log.info(
            "model=%s R2=%.4f MAPE=%.2f%% RMSE=%.0f MAE=%.0f (train=%d, test=%d)",
            r.model_name,
            r.metrics["r2"],
            r.metrics["mape_pct"],
            r.metrics["rmse_rub"],
            r.metrics["mae_rub"],
            r.train_rows,
            r.test_rows,
        )
    return results
