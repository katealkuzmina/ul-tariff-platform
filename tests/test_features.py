from datetime import date

import numpy as np
import pandas as pd


def _ensure_data(conn):
    from etl.pipeline import run_etl

    run_etl(conn, date(2026, 7, 1), date(2026, 10, 26))


def test_parse_region():
    from ml.features import parse_region

    assert parse_region("Казань, Республика Татарстан") == ("Казань", "Республика Татарстан")
    assert parse_region("Екатеринбург, Свердловская обл.") == ("Екатеринбург", "Свердловская обл.")
    assert parse_region("Москва, г. Москва") == ("Москва", "г. Москва")
    city, region = parse_region("Ханты-Мансийск")
    assert city == "Ханты-Мансийск"
    assert region in (None, "")


def test_cyclical_proximity_dec_jan():
    from ml.features import add_cyclical

    df = pd.DataFrame(
        {"loading_date": pd.to_datetime(["2025-12-31", "2026-01-01", "2026-06-30"])}
    )
    out = add_cyclical(df)
    a = out.loc[0, ["doy_sin", "doy_cos"]].to_numpy()
    b = out.loc[1, ["doy_sin", "doy_cos"]].to_numpy()
    c = out.loc[2, ["doy_sin", "doy_cos"]].to_numpy()
    assert np.linalg.norm(a - b) < np.linalg.norm(a - c)
    assert np.linalg.norm(a - b) < np.linalg.norm(b - c)
    # sin/cos на единичной окружности
    for col in ["month", "dow", "doy"]:
        r = np.sqrt(out[f"{col}_sin"] ** 2 + out[f"{col}_cos"] ** 2)
        assert np.allclose(r, 1.0, atol=1e-6)


def test_no_leakage_columns(conn):
    from ml.features import FORBIDDEN, build_xy, load_dataset

    _ensure_data(conn)
    df = load_dataset(conn)
    X, y, meta = build_xy(df)
    assert not (FORBIDDEN & set(X.columns))
    assert y.notna().all()
    assert len(X) == len(df) > 0
    assert {"price_id", "loading_date"} <= set(meta.columns)


def test_regions_and_coordinates_present(conn):
    from ml.features import FEATURE_COLUMNS, build_xy, load_dataset

    _ensure_data(conn)
    df = load_dataset(conn)
    X, y, meta = build_xy(df)
    for c in [
        "origin_region",
        "destination_region",
        "origin_latitude",
        "destination_longitude",
        "body_group",
        "distance",
        "total_weight",
        "total_volume",
        "weight_category",
        "volume_category",
        "month_sin",
        "month_cos",
        "dow_sin",
        "dow_cos",
        "doy_sin",
        "doy_cos",
        "year",
        "month",
        "dayofweek",
        "dayofyear",
    ]:
        assert c in X.columns, c
    assert list(X.columns) == FEATURE_COLUMNS
    # категориальные признаки без NaN
    for c in ["origin_region", "destination_region", "body_group", "weight_category", "volume_category"]:
        assert X[c].notna().all(), c
    # одна строка на сделку
    assert meta.price_id.is_unique
