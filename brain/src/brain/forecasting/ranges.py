"""The 80% low/high range (README 4.7, research R-09, P-2): the same rule for both models.

- With at least `range_min_errors` backtest errors: low = min(ŷ, max(0, ŷ + q10)),
  high = max(ŷ, ŷ + q90), from the 10th/90th percentiles of the errors (all of them, even if
  fewer than 28).
- With fewer: low = max(0, ŷ − sd), high = ŷ + sd, sd = the sample sd of the last 28 closed days.

So always 0 ≤ low ≤ ŷ ≤ high (FR-016).
"""

import numpy as np

from brain.config import Settings


def bounds(
    yhat: np.ndarray, errors: np.ndarray, sd: float, settings: Settings
) -> tuple[np.ndarray, np.ndarray, float | None, float | None]:
    if len(errors) >= settings.range_min_errors:
        q10 = float(np.percentile(errors, settings.range_low_quantile * 100))
        q90 = float(np.percentile(errors, settings.range_high_quantile * 100))
        low = np.minimum(yhat, np.maximum(0.0, yhat + q10))
        high = np.maximum(yhat, yhat + q90)
        return low, high, q10, q90
    low = np.maximum(0.0, yhat - sd)
    high = yhat + sd
    return low, high, None, None
