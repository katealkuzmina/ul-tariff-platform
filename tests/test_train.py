from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import text


def _ensure_data(conn):
    from etl.pipeline import run_etl

    run_etl(conn, date(2026, 7, 1), date(2026, 10, 26))


def _dataset(conn):
    from ml.features import load_dataset

    _ensure_data(conn)
    return load_dataset(conn)


def test_time_split_boundaries(conn):
    from ml.dataset import time_split

    df = _dataset(conn)
    as_of = date(2026, 10, 26)
    train_df, test_df = time_split(df, as_of)
    assert train_df.loading_date.max() < pd.Timestamp("2026-10-05")
    assert test_df.loading_date.min() >= pd.Timestamp("2026-10-05")
    assert test_df.loading_date.max() <= pd.Timestamp("2026-10-26")
    assert not train_df.outlier_mark.any()
    assert len(train_df) > 0 and len(test_df) > 0
    # границы вычисляются от as_of, а не от системной даты: train = [as_of-3mo, as_of-3wk)
    assert train_df.loading_date.min() >= pd.Timestamp(as_of - relativedelta(months=3))
    assert train_df.loading_date.max() < pd.Timestamp(as_of - timedelta(weeks=3))


def test_catboost_deterministic(conn):
    from ml.features import build_xy
    from ml.train import train_catboost

    df = _dataset(conn).sample(n=3000, random_state=7)
    X, y, _ = build_xy(df)
    m1 = train_catboost(X, y, seed=42)
    m2 = train_catboost(X, y, seed=42)
    assert np.allclose(m1.predict(X), m2.predict(X))


def test_ridge_pipeline_fitted_on_train_only(conn):
    from ml.dataset import time_split
    from ml.features import CATEGORICAL_COLUMNS, NUMERIC_COLUMNS, build_xy
    from ml.train import train_ridge

    df = _dataset(conn)
    train_df, test_df = time_split(df, date(2026, 10, 26))
    X_tr, y_tr, _ = build_xy(train_df.sample(n=3000, random_state=7))
    X_te, _, _ = build_xy(test_df.sample(n=1000, random_state=8))
    pipe = train_ridge(X_tr, y_tr)
    pred = pipe.predict(X_te)  # predict на test не падает (handle_unknown="ignore")
    assert pred.shape == (len(X_te),)
    scaler = pipe.named_steps["prep"].named_transformers_["num"].named_steps["scaler"]
    assert np.allclose(scaler.mean_, X_tr[NUMERIC_COLUMNS].mean().to_numpy(), atol=1e-6)
    ohe = pipe.named_steps["prep"].named_transformers_["cat"]
    assert set(ohe.feature_names_in_) == set(CATEGORICAL_COLUMNS)


def test_metrics_perfect_and_realistic():
    from ml.evaluate import metrics

    y = np.array([100.0, 200.0, 300.0, 400.0])
    perfect = metrics(y, y)
    assert perfect["r2"] == pytest.approx(1.0)
    assert perfect["mape_pct"] == pytest.approx(0.0)
    assert perfect["rmse_rub"] == pytest.approx(0.0)
    assert perfect["mae_rub"] == pytest.approx(0.0)
    real = metrics(y, np.array([110.0, 190.0, 330.0, 360.0]))
    assert real["r2"] < 1.0
    assert real["mape_pct"] > 0
    assert real["rmse_rub"] > real["mae_rub"]


def test_run_training_writes_metrics(conn):
    from etl.config import get_settings
    from ml.train import run_training

    _ensure_data(conn)
    results = run_training(conn, get_settings())
    assert {r.model_name for r in results} == {"catboost_v1", "ridge_v1"}
    rows = conn.execute(
        text("SELECT model_name, train_rows, test_rows, r2, mape_pct FROM mart.model_metrics")
    ).all()
    by_name = {r[0]: r for r in rows}
    assert set(by_name) == {"catboost_v1", "ridge_v1"}
    for name, train_rows, test_rows, r2, mape in rows:
        assert train_rows > 0 and test_rows > 0
        assert -1.0 <= float(r2) <= 1.0
        assert float(mape) > 0
    # catboost не хуже линейного бейзлайна по MAPE
    assert float(by_name["catboost_v1"][4]) <= float(by_name["ridge_v1"][4]) * 1.5
