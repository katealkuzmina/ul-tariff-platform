from datetime import date

import pytest
from sqlalchemy import text


@pytest.fixture()
def trained_model(conn):
    from etl.config import get_settings
    from etl.pipeline import run_etl
    from ml.train import run_training

    run_etl(conn, date(2026, 7, 1), date(2026, 12, 31))
    return run_training(conn, get_settings())


def test_predictions_written_and_nullable_actual(conn, trained_model):
    from ml.predict import run_scoring

    n = run_scoring(conn, "catboost_v1", date(2026, 10, 26))
    assert n > 0
    fut = conn.execute(
        text(
            """SELECT count(*) FROM mart.ml_price_predictions WHERE model_name='catboost_v1'
               AND loading_date > DATE '2026-10-26'
               AND (actual_price_rub IS NOT NULL OR abs_error_rub IS NOT NULL OR ape_pct IS NOT NULL)"""
        )
    ).scalar()
    assert fut == 0
    hist = conn.execute(
        text(
            """SELECT count(*) FROM mart.ml_price_predictions WHERE model_name='catboost_v1'
               AND loading_date <= DATE '2026-10-26'
               AND (actual_price_rub IS NULL OR predicted_price_rub IS NULL)"""
        )
    ).scalar()
    assert hist == 0
    # в тестовом окне actual == факту из core
    mismatch = conn.execute(
        text(
            """SELECT count(*) FROM mart.ml_price_predictions mpp
               JOIN core.prices_clean pc ON pc.price_id = mpp.price_id
               WHERE mpp.model_name='catboost_v1' AND mpp.loading_date <= DATE '2026-10-26'
                 AND abs(mpp.actual_price_rub - pc.price_rub) > 0.01"""
        )
    ).scalar()
    assert mismatch == 0


def test_scoring_idempotent(conn, trained_model):
    from ml.predict import run_scoring

    n1 = run_scoring(conn, "catboost_v1", date(2026, 10, 26))
    n2 = run_scoring(conn, "catboost_v1", date(2026, 10, 26))
    assert n1 == n2 > 0


def test_predictions_cover_test_window_and_future(conn, trained_model):
    from ml.predict import run_scoring

    run_scoring(conn, "catboost_v1", date(2026, 10, 26))
    expected_hist = conn.execute(
        text(
            """SELECT count(*) FROM core.prices_clean
               WHERE is_fact AND NOT complex AND price_rub IS NOT NULL
                 AND loading_date BETWEEN DATE '2026-10-05' AND DATE '2026-10-26'"""
        )
    ).scalar()
    expected_fut = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean WHERE loading_date > DATE '2026-10-26'"
        )
    ).scalar()
    hist = conn.execute(
        text(
            """SELECT count(*) FROM mart.ml_price_predictions
               WHERE model_name='catboost_v1' AND loading_date <= DATE '2026-10-26'"""
        )
    ).scalar()
    fut = conn.execute(
        text(
            """SELECT count(*) FROM mart.ml_price_predictions
               WHERE model_name='catboost_v1' AND loading_date > DATE '2026-10-26'"""
        )
    ).scalar()
    assert hist == expected_hist > 0
    assert fut == expected_fut > 0
