"""Weekly seasonal-naive (README 4.2, research R-07): ŷ(o + h) = y(o + h − 7·⌈h/7⌉), so the last
week repeats. With fewer than `short_days` closed days there is no week to repeat, so every day
is forecast as the average of the closed days so far (spec Edge Cases, short history)."""

import math

import numpy as np


def forecast(y: np.ndarray, horizon: int, short_days: int) -> np.ndarray:
    n = len(y)
    if n == 0:
        return np.zeros(horizon)
    if n < short_days or n < 7:
        return np.full(horizon, float(np.mean(y)))
    out = np.empty(horizon)
    for h in range(1, horizon + 1):
        out[h - 1] = y[n - 1 + h - 7 * math.ceil(h / 7)]
    return out
