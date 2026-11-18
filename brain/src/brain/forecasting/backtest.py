"""The backtest (README 4.7: the last 4 weeks; research R-07): two 14-day origins, so every
backtest forecast has the real 14-day horizon.

- origin A = the day before the window: forecasts days 1-14 of the window;
- origin B = day 14 of the window: forecasts days 15-28.

Each origin sees only data up to itself. Errors are taken only where the product had at least one
closed day at the origin, so a product younger than the window has fewer errors (or none).
"""

from datetime import date, timedelta

import numpy as np

from brain.config import Settings
from brain.forecasting import seasonal_naive
from brain.forecasting.series import Series


def origins(end: date, backtest_days: int, horizon: int) -> list[date]:
    first = end - timedelta(days=backtest_days)
    return [first + timedelta(days=k) for k in range(0, backtest_days, horizon)]


def wape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    """Σ|y − ŷ| / Σy; undefined when there are no days or no sales."""
    if len(actual) == 0:
        return None
    total = float(np.sum(actual))
    if total <= 0:
        return None
    return float(np.sum(np.abs(actual - predicted)) / total)


def targets(series: Series, origin: date, end: date, horizon: int) -> list[date]:
    """The days origin+1 … origin+horizon that are on or before `end`, if the product existed at
    the origin."""
    if origin < series.start:
        return []
    return [
        origin + timedelta(days=h)
        for h in range(1, horizon + 1)
        if origin + timedelta(days=h) <= end
    ]


def seasonal_naive_backtest(
    series: Series, end: date, settings: Settings
) -> tuple[np.ndarray, np.ndarray]:
    actual: list[float] = []
    predicted: list[float] = []
    horizon = settings.forecast_horizon_days
    for origin in origins(end, settings.backtest_days, horizon):
        days = targets(series, origin, end, horizon)
        if not days:
            continue
        history = series.y[: series.index_of(origin) + 1]
        forecast = seasonal_naive.forecast(history, horizon, settings.short_history_days)
        for day in days:
            actual.append(float(series.y[series.index_of(day)]))
            predicted.append(float(forecast[(day - origin).days - 1]))
    return np.array(actual), np.array(predicted)
