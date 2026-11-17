"""US2 building blocks: series (T022), seasonal-naive and backtest (T023), features (T024),
ranges (T025) and artifacts (T026). Written before the implementation.

One correction to tasks.md T023: with the approved two 14-day backtest origins, a product with
10 closed days did not exist at either origin, so it has **0** test-period errors (not 3). Its
WAPE is undefined, it uses seasonal-naive, and its range is ± its standard deviation (fewer than
7 errors). The tests below check that.
"""

import math
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from brain.config import Settings
from brain.forecasting import backtest, features, ranges, seasonal_naive
from brain.forecasting.series import build_series

END = date(2026, 11, 17)  # the newest closed day
SETTINGS = Settings()


def _rows(product: str, values: list[int], last: date = END, statuses: dict | None = None):
    first = last - timedelta(days=len(values) - 1)
    return [
        (product, first + timedelta(days=i), v, (statuses or {}).get(i, "closed"))
        for i, v in enumerate(values)
    ]


# ---------------------------------------------------------------- T022 series


def test_series_uses_closed_days_clips_at_zero_and_fills_gaps() -> None:
    rows = _rows("P001", [5, -2, 7, 3])
    del rows[2]  # a closed day with no row counts as 0
    rows.append(("P001", END + timedelta(days=1), 99, "open"))  # today: never in the series
    s = build_series(rows, END)["P001"]
    assert s.start == END - timedelta(days=3) and s.end == END
    assert s.y.tolist() == [5, 0, 0, 3]  # max(net, 0); the missing day is 0
    assert s.net.tolist() == [5, -2, 0, 3]


def test_series_ends_at_the_newest_closed_day() -> None:
    rows = _rows("P001", [1, 2, 3], last=END - timedelta(days=1)) + [("P001", END, 4, "open")]
    s = build_series(rows, END - timedelta(days=1))["P001"]
    assert s.end == END - timedelta(days=1) and s.y.tolist() == [1, 2, 3]


# ---------------------------------------------------------------- T023 seasonal-naive, backtest


def test_seasonal_naive_repeats_last_week() -> None:
    y = np.arange(1, 22, dtype=float)  # 21 days: last week is 15..21
    out = seasonal_naive.forecast(y, 14, SETTINGS.short_history_days)
    assert out.tolist() == [15, 16, 17, 18, 19, 20, 21] * 2


def test_seasonal_naive_with_under_7_days_is_the_average() -> None:
    out = seasonal_naive.forecast(np.array([2.0, 4.0, 6.0, 8.0, 10.0]), 14, 7)
    assert out.tolist() == [6.0] * 14


def test_backtest_origins_and_wape() -> None:
    assert backtest.origins(END, 28, 14) == [END - timedelta(days=28), END - timedelta(days=14)]
    assert backtest.wape(np.array([10.0, 10.0]), np.array([8.0, 13.0])) == pytest.approx(0.25)
    assert backtest.wape(np.array([0.0, 0.0]), np.array([1.0, 2.0])) is None
    assert backtest.wape(np.array([]), np.array([])) is None


def test_seasonal_naive_backtest_covers_the_last_28_days() -> None:
    values = [(i % 7) * 3 + 10 for i in range(90)]
    s = build_series(_rows("P001", values), END)["P001"]
    actual, predicted = backtest.seasonal_naive_backtest(s, END, SETTINGS)
    assert len(actual) == 28
    assert np.array_equal(actual, predicted)  # a perfect weekly pattern


def test_a_10_day_product_has_no_backtest_errors() -> None:
    s = build_series(_rows("P009", [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]), END)["P009"]
    actual, predicted = backtest.seasonal_naive_backtest(s, END, SETTINGS)
    assert len(actual) == 0 and backtest.wape(actual, predicted) is None
    assert seasonal_naive.forecast(s.y, 14, 7).tolist() == [1, 5, 9, 2, 6, 5, 3] * 2  # last week


# ---------------------------------------------------------------- T024 features


def test_features_at_an_origin() -> None:
    values = list(range(1, 61))  # y = 1..60 on days 0..59
    s = build_series(_rows("P007", values), END)["P007"]
    origin = END  # index 59
    X, scale, dates = features.rows_for_origin(s, origin, 14)
    assert features.FEATURES == [
        "product", "dow", "h", "seasonal_naive", "dow_mean_4w", "mean_7", "sd_28", "log_scale",
    ]
    mean28 = statistics.mean(values[-28:])
    assert scale.tolist() == [mean28] * 14
    row3 = X[2]  # h = 3: target day index 62, last week's same weekday = index 55 (value 56)
    assert row3[0] == 7 and row3[2] == 3
    assert row3[1] == (END + timedelta(days=3)).weekday()
    assert row3[3] == pytest.approx(56 / mean28)
    # same weekday over the last 4 weeks up to the origin: indexes 55, 48, 41, 34
    assert row3[4] == pytest.approx(statistics.mean([56, 49, 42, 35]) / mean28)
    row10 = X[9]  # h = 10: target index 69, 7·⌈10/7⌉ = 14 back = index 55
    assert row10[3] == pytest.approx(56 / mean28)
    assert row3[5] == pytest.approx(statistics.mean(values[-7:]) / mean28)
    assert row3[6] == pytest.approx(statistics.stdev(values[-28:]) / mean28)
    assert row3[7] == pytest.approx(math.log1p(mean28))
    assert dates[0] == END + timedelta(days=1) and len(dates) == 14


def test_training_rows_never_read_past_the_cut() -> None:
    values = list(range(1, 61))
    s = build_series(_rows("P007", values), END)["P007"]
    cut = END - timedelta(days=20)
    X, y = features.rows_for_training([s], cut, 14)
    # every target is on or before the cut: the largest target value is the cut day's value
    scales = np.exp(X[:, 7]) - 1
    assert (y * scales).max() == pytest.approx(values[-21])
    assert len(X) > 0 and X.shape[1] == 8


def test_the_scale_is_at_least_one() -> None:
    s = build_series(_rows("P007", [0] * 40), END)["P007"]
    _, scale, _ = features.rows_for_origin(s, END, 14)
    assert scale.min() == 1.0


# ---------------------------------------------------------------- T025 ranges


def test_ranges_from_errors() -> None:
    yhat = np.array([10.0, 2.0])
    errors = np.array([-5.0, -1.0, 0.0, 1.0, 2.0, 3.0, 8.0, 4.0, -2.0, 1.0])
    low, high, q10, q90 = ranges.bounds(yhat, errors, sd=3.0, settings=SETTINGS)
    assert q10 == pytest.approx(np.percentile(errors, 10)) and q90 == pytest.approx(np.percentile(errors, 90))
    assert low.tolist() == pytest.approx([max(0, 10 + q10), max(0.0, min(2.0, 2 + q10))])
    assert all(0 <= lo <= y <= hi for lo, y, hi in zip(low, yhat, high))


def test_ranges_cover_80_percent_of_28_errors() -> None:
    rng = np.random.default_rng(1)
    errors = rng.normal(0, 3, 28)
    _, _, q10, q90 = ranges.bounds(np.array([20.0]), errors, sd=3.0, settings=SETTINGS)
    inside = ((errors >= q10) & (errors <= q90)).sum()
    assert abs(inside - 0.8 * 28) <= 1.5


def test_short_history_ranges() -> None:
    yhat = np.array([5.0, 1.0])
    low, high, _, _ = ranges.bounds(yhat, np.array([1.0, -1.0, 2.0]), sd=2.0, settings=SETTINGS)
    assert low.tolist() == [3.0, 0.0] and high.tolist() == [7.0, 3.0]
    errors12 = np.arange(-6.0, 6.0)
    _, _, q10, _ = ranges.bounds(yhat, errors12, sd=2.0, settings=SETTINGS)
    assert q10 == pytest.approx(np.percentile(errors12, 10))


# ---------------------------------------------------------------- T026 artifacts (no pickle)


def test_no_pickle_import_anywhere_in_the_brain() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    banned = re.compile(r"^\s*(import|from)\s+(pickle|cPickle|joblib|cloudpickle|dill)\b", re.MULTILINE)
    for path in src.rglob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), path
