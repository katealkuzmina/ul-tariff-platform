"""Хронологическое разбиение на train/test (Time-Based Split).

Границы отсчитываются от фиксированной даты снимка as_of, а не от системной
даты: train = [as_of - 3 месяца, as_of - 3 недели), test = [as_of - 3 недели, as_of].
Граница test_start входит только в test. Случайное перемешивание запрещено.
Обучающая выборка дополнительно очищается от outlier_mark = true.
"""

from datetime import date, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta


def split_bounds(as_of: date) -> tuple[date, date, date]:
    train_start = as_of - relativedelta(months=3)
    test_start = as_of - timedelta(weeks=3)
    return train_start, test_start, as_of


def time_split(df: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_start, test_start, test_end = split_bounds(as_of)
    loading = pd.to_datetime(df["loading_date"])
    train_mask = (loading >= pd.Timestamp(train_start)) & (loading < pd.Timestamp(test_start))
    test_mask = (loading >= pd.Timestamp(test_start)) & (loading <= pd.Timestamp(test_end))
    train_df = df[train_mask & ~df["outlier_mark"]]
    test_df = df[test_mask]
    return train_df, test_df
