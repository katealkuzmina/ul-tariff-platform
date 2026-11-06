"""Метрики качества регрессии на отложенной выборке."""

import numpy as np
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    r2_score,
    root_mean_squared_error,
)


def metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "mape_pct": float(mean_absolute_percentage_error(y_true, y_pred)) * 100.0,
        "rmse_rub": float(root_mean_squared_error(y_true, y_pred)),
        "mae_rub": float(mean_absolute_error(y_true, y_pred)),
    }
