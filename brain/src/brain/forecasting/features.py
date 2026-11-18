"""The LightGBM feature set (research R-08, P-1): one global "direct" model. Each row is one
(product, origin o, horizon h); the target day is t = o + h. Every feature is known at the origin,
so the 14 forecast days need no recursion. Nothing needs more than 28 days of history; there are
no yearly, price, promotion or stock features (README Section 9)."""

import math
from datetime import date, timedelta

import numpy as np

from brain.forecasting.series import Series

FEATURES = [
    "product",
    "dow",
    "h",
    "seasonal_naive",
    "dow_mean_4w",
    "mean_7",
    "sd_28",
    "log_scale",
]
CATEGORICAL = [0, 1]
WINDOW = 28


def product_code(product_id: str) -> int:
    """A stable category code: the number in the readable ID (P003 -> 3)."""
    return int(product_id[1:])


def _origin_stats(y: np.ndarray, oi: int) -> tuple[float, float, float]:
    """scale = max(mean of the last 28 days to the origin, 1); the 7-day mean; the 28-day sd."""
    lo = max(0, oi - WINDOW + 1)
    last28 = y[lo : oi + 1]
    last7 = y[max(0, oi - 6) : oi + 1]
    scale = max(float(np.mean(last28)), 1.0)
    sd = float(np.std(last28, ddof=1)) if len(last28) > 1 else 0.0
    return scale, float(np.mean(last7)), sd


def _row(series: Series, oi: int, h: int, stats: tuple[float, float, float]) -> list[float]:
    scale, mean7, sd28 = stats
    ti = oi + h
    k = math.ceil(h / 7)
    lag = ti - 7 * k
    sn = series.y[lag] / scale if lag >= 0 else math.nan
    same = [series.y[ti - 7 * j] for j in range(k, k + 4) if ti - 7 * j >= 0]
    dow_mean = float(np.mean(same)) / scale if same else math.nan
    return [
        float(product_code(series.product_id)),
        float(series.date_at(ti).weekday()),
        float(h),
        sn,
        dow_mean,
        mean7 / scale,
        sd28 / scale,
        math.log1p(scale),
    ]


def rows_for_training(
    series_list: list[Series], cut: date, horizon: int
) -> tuple[np.ndarray, np.ndarray]:
    """Training rows whose target is on or before `cut`, from origins with 28 days behind them."""
    X: list[list[float]] = []
    y: list[float] = []
    for series in series_list:
        last = min(series.index_of(cut), len(series) - 1)
        for oi in range(WINDOW - 1, last):
            stats = _origin_stats(series.y, oi)
            for h in range(1, horizon + 1):
                if oi + h > last:
                    break
                X.append(_row(series, oi, h, stats))
                y.append(series.y[oi + h] / stats[0])
    return np.array(X, dtype=float).reshape(-1, len(FEATURES)), np.array(y, dtype=float)


def rows_for_origin(
    series: Series, origin: date, horizon: int
) -> tuple[np.ndarray, np.ndarray, list[date]]:
    """Rows to forecast origin+1 … origin+horizon, with each row's scale and target date."""
    oi = series.index_of(origin)
    stats = _origin_stats(series.y, oi)
    X = np.array([_row(series, oi, h, stats) for h in range(1, horizon + 1)], dtype=float)
    return (
        X,
        np.full(horizon, stats[0]),
        [origin + timedelta(days=h) for h in range(1, horizon + 1)],
    )
