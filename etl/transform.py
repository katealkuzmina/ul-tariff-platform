"""Правила Data Quality, весовые/объёмные категории и конвертация валют.

Чистые функции: скалярные обёртки для юнит-тестов и векторизованные
pandas-версии для пайплайна. Курсы валют передаются отдельным набором
дат публикации (num_code, setting_date), доступных в справочнике.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping, Optional, Set, Tuple

import numpy as np
import pandas as pd

REASON_CODES: Tuple[str, ...] = (
    "INVALID_PRICE",
    "INVALID_PRICE_RANGE",
    "INVALID_DISTANCE",
    "INVALID_WEIGHT",
    "INVALID_VOLUME",
    "CITY_NOT_FOUND",
    "FX_RATE_MISSING",
)

RUB_CODE = "643"
RUB_MAX_PRICE = 1000.0  # source-validation диапазон для рублёвых ставок
FTL_MAX_VOLUME = 120.0


def _round_1t(weight: float) -> Decimal:
    return Decimal(str(weight)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fill_weight_category(weight: Optional[float]) -> Optional[str]:
    """Категория веса по округлению до 0.1 т (HALF_UP, как numeric в PostgreSQL)."""
    if weight is None or pd.isna(weight):
        return None
    w = _round_1t(weight)
    if w >= Decimal("30.0"):
        return "G20T"
    if w >= Decimal("10.0"):
        return "FTL"
    if w >= Decimal("5.0"):
        return "10T"
    if w >= Decimal("2.5"):
        return "5T"
    if w >= Decimal("0.5"):
        return "L5T"
    return "OTH"


def fill_volume_category(volume: Optional[float]) -> Optional[str]:
    if volume is None or pd.isna(volume):
        return None
    if 0 < volume <= FTL_MAX_VOLUME:
        return "FTL"
    return "OTH"


def validate_row(
    r: Mapping,
    city_gc_ids: Set[int],
    fx_dates: Optional[Set[Tuple[str, object]]] = None,
) -> Optional[str]:
    """Первая сработавшая причина отбраковки (приоритет = порядок REASON_CODES)."""
    if r["price"] <= 0:
        return "INVALID_PRICE"
    if r["currency_code"] == RUB_CODE and r["price"] <= RUB_MAX_PRICE:
        return "INVALID_PRICE_RANGE"
    if r["distance"] <= 0:
        return "INVALID_DISTANCE"
    if r["total_weight"] < 0:
        return "INVALID_WEIGHT"
    if r["total_volume"] < 0:
        return "INVALID_VOLUME"
    if r["loading_city_gcid"] not in city_gc_ids or r["unloading_city_gcid"] not in city_gc_ids:
        return "CITY_NOT_FOUND"
    if r["currency_code"] != RUB_CODE:
        nrd = r.get("nearest_rate_date")
        if nrd is None or (fx_dates is not None and (r["currency_code"], nrd) not in fx_dates):
            return "FX_RATE_MISSING"
    return None


def convert_price_rub(
    price: float, currency_code: str, rate: Optional[float]
) -> Optional[float]:
    """Приведение ставки к RUB без НДС; курс для RUB равен 1."""
    if currency_code == RUB_CODE:
        return float(price)
    if rate is None:
        return None
    return float(price) * float(rate)


def add_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Заполнение weight_category / volume_category (пропуски и пересчёт)."""
    out = df.copy()
    out["weight_category"] = [
        fill_weight_category(w) for w in out["total_weight"]
    ]
    out["volume_category"] = [
        fill_volume_category(v) for v in out["total_volume"]
    ]
    return out


def validate_frame(
    df: pd.DataFrame, city_gc_ids: Set[int], fx_dates: Set[Tuple[str, object]]
) -> pd.Series:
    """Векторизованная валидация: Series с кодом причины или None для валидных строк."""
    reasons = pd.Series(np.full(len(df), None, dtype=object), index=df.index)
    rub = df["currency_code"] == RUB_CODE
    is_fx = ~rub
    fx_date_ok = (
        df["nearest_rate_date"].notna()
        & pd.Series(
            [
                (cur, d) in fx_dates
                for cur, d in zip(df["currency_code"], df["nearest_rate_date"])
            ],
            index=df.index,
        )
    )
    checks = [
        ("INVALID_PRICE", df["price"] <= 0),
        ("INVALID_PRICE_RANGE", rub & (df["price"] <= RUB_MAX_PRICE)),
        ("INVALID_DISTANCE", df["distance"] <= 0),
        ("INVALID_WEIGHT", df["total_weight"] < 0),
        ("INVALID_VOLUME", df["total_volume"] < 0),
        (
            "CITY_NOT_FOUND",
            ~df["loading_city_gcid"].isin(city_gc_ids)
            | ~df["unloading_city_gcid"].isin(city_gc_ids),
        ),
        ("FX_RATE_MISSING", is_fx & ~fx_date_ok),
    ]
    for code, mask in checks:
        reasons = reasons.mask(mask & reasons.isna(), code)
    return reasons
