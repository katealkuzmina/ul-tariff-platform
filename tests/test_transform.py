from datetime import date

import pytest


def row(**kw):
    base = dict(
        price=5000.0,
        currency_code="643",
        distance=100.0,
        total_weight=10.0,
        total_volume=50.0,
        loading_city_gcid=1001,
        unloading_city_gcid=1002,
        nearest_rate_date=date(2026, 8, 1),
    )
    base.update(kw)
    return base


@pytest.mark.parametrize(
    "w,expected",
    [
        (30.0, "G20T"),
        (29.96, "G20T"),
        (10.0, "FTL"),
        (9.99, "FTL"),  # round(9.99, 0.1) = 10.0 -> FTL (округление до бакета)
        (5.0, "10T"),
        (2.5, "5T"),
        (2.49, "5T"),  # round(2.49, 0.1) = 2.5 -> 5T
        (0.5, "L5T"),
        (0.49, "L5T"),  # round(0.49, 0.1) = 0.5 -> L5T
        (0.0, "OTH"),
        (0.04, "OTH"),
        (35.04, "G20T"),
    ],
)
def test_weight_category_boundaries(w, expected):
    from etl.transform import fill_weight_category

    assert fill_weight_category(w) == expected


@pytest.mark.parametrize(
    "v,expected",
    [(120.0, "FTL"), (0.1, "FTL"), (0.0, "OTH"), (121.0, "OTH"), (120.4, "OTH"), (82.0, "FTL")],
)
def test_volume_category_boundaries(v, expected):
    from etl.transform import fill_volume_category

    assert fill_volume_category(v) == expected


def test_validate_row_reasons():
    from etl.transform import validate_row

    cities = {1001, 1002}
    fx_dates = {("840", date(2026, 8, 1)), ("978", date(2026, 8, 1))}
    assert validate_row(row(price=0.0), cities, fx_dates) == "INVALID_PRICE"
    assert validate_row(row(price=-5.0), cities, fx_dates) == "INVALID_PRICE"
    assert validate_row(row(price=1000.0), cities, fx_dates) == "INVALID_PRICE_RANGE"
    assert validate_row(row(price=1000.01), cities, fx_dates) is None
    assert validate_row(row(distance=0.0), cities, fx_dates) == "INVALID_DISTANCE"
    assert validate_row(row(distance=-1.0), cities, fx_dates) == "INVALID_DISTANCE"
    assert (
        validate_row(row(currency_code="840", nearest_rate_date=None), cities, fx_dates)
        == "FX_RATE_MISSING"
    )
    assert (
        validate_row(row(currency_code="840", nearest_rate_date=date(2026, 8, 2)), cities, fx_dates)
        == "FX_RATE_MISSING"
    )
    assert (
        validate_row(row(currency_code="840", nearest_rate_date=date(2026, 8, 1)), cities, fx_dates)
        is None
    )
    # RUB не требует курса и nearest_rate_date
    assert validate_row(row(nearest_rate_date=None), cities, fx_dates) is None
    assert validate_row(row(loading_city_gcid=9999), cities, fx_dates) == "CITY_NOT_FOUND"
    assert validate_row(row(unloading_city_gcid=9999), cities, fx_dates) == "CITY_NOT_FOUND"
    assert validate_row(row(total_weight=-0.1), cities, fx_dates) == "INVALID_WEIGHT"
    assert validate_row(row(total_volume=-1.0), cities, fx_dates) == "INVALID_VOLUME"
    assert validate_row(row(), cities, fx_dates) is None


def test_validate_row_priority_first_reason():
    from etl.transform import validate_row

    cities = {1001, 1002}
    fx_dates = set()
    # несколько нарушений — возвращается первая по каноническому порядку
    assert validate_row(row(price=0.0, distance=0.0), cities, fx_dates) == "INVALID_PRICE"
    assert (
        validate_row(row(price=100.0, total_weight=-1.0, total_volume=-1.0), cities, fx_dates)
        == "INVALID_PRICE_RANGE"
    )
    assert (
        validate_row(row(distance=0.0, total_weight=-1.0), cities, fx_dates) == "INVALID_DISTANCE"
    )


def test_reason_codes_canonical_order():
    from etl.transform import REASON_CODES

    assert list(REASON_CODES) == [
        "INVALID_PRICE",
        "INVALID_PRICE_RANGE",
        "INVALID_DISTANCE",
        "INVALID_WEIGHT",
        "INVALID_VOLUME",
        "CITY_NOT_FOUND",
        "FX_RATE_MISSING",
    ]


def test_convert_price_rub():
    from etl.transform import convert_price_rub

    assert convert_price_rub(100.0, "643", None) == 100.0
    assert convert_price_rub(100.0, "840", 90.5) == 9050.0
    assert convert_price_rub(100.0, "978", 100.0) == 10000.0


def test_fill_categories_frame_vectorized():
    import pandas as pd

    from etl.transform import add_categories

    df = pd.DataFrame(
        {
            "total_weight": [30.0, 9.99, 2.49, 0.3, None],
            "total_volume": [120.0, 121.0, 50.0, 0.0, None],
        }
    )
    out = add_categories(df)
    assert out.weight_category.tolist()[:4] == ["G20T", "FTL", "5T", "OTH"]
    assert out.volume_category.tolist()[:4] == ["FTL", "OTH", "FTL", "OTH"]
    assert pd.isna(out.weight_category.iloc[4]) and pd.isna(out.volume_category.iloc[4])
