"""Days of cover, risk, safety stock and the order quantity (FR-022 to FR-023, data-model
"How the numbers are computed"). Every intermediate number is written out. Written first."""

import math

import pytest

from brain.risk import (
    days_of_cover,
    forecast_over,
    order_quantity,
    raise_level,
    risk_level,
    safety_stock,
)


def test_days_of_cover_walks_the_forecast() -> None:
    assert days_of_cover(10, [2, 2, 8] + [1] * 11) == pytest.approx(2.75)  # 1 + 1 + 6/8
    # Stock outlasting 14 days: 14 + leftover ÷ the 14-day mean.
    forecast = [2.0] * 14  # uses 28, mean 2
    assert days_of_cover(40, forecast) == pytest.approx(14 + 12 / 2)
    assert days_of_cover(5, [0.0] * 14) is None  # unlimited
    assert days_of_cover(0, [3.0] * 14) == 0.0


@pytest.mark.parametrize(
    ("cover", "lead", "expected"),
    [(2.75, 3, "high"), (3.0, 3, "medium"), (4.99, 3, "medium"), (5.0, 3, "low"), (None, 3, "low")],
)
def test_risk_from_cover_and_lead_time(cover, lead, expected) -> None:
    assert risk_level(cover, lead) == expected


def test_a_spike_raises_one_level_never_above_high() -> None:
    assert raise_level("low") == "medium"
    assert raise_level("medium") == "high"
    assert raise_level("high") == "high"
    assert risk_level(10.0, None) is None


def test_safety_stock() -> None:
    assert safety_stock(sd=4.47, mean=20.0, lead=7, z=1.65, days=28) == math.ceil(1.65 * 4.47 * math.sqrt(7))
    assert safety_stock(sd=0.0, mean=3.2, lead=5, z=1.65, days=1) == 4  # fewer than 2 days: ceil(mean)


def test_forecast_over_lead_time_from_today() -> None:
    forecast = [float(d) for d in range(1, 15)]  # 1..14
    assert forecast_over(forecast, 3) == 6  # today + 2 days
    assert forecast_over(forecast, 16) == sum(forecast) + 2 * (sum(forecast) / 14)


@pytest.mark.parametrize(
    ("fol", "ss", "available", "open_po", "pack", "maximum", "target", "raw", "order"),
    [
        # P003-like: ceil(140 + 20) = 160; 160 − 60 − 0 = 100 → 108 (pack 12) ≤ 240
        (140.0, 20, 60, 0, 12, 240, 160, 100, 108),
        # P011-like: ceil(50.4 + 12) = 63; 63 − 25 − 0 = 38 → 40 (pack 5)
        (50.4, 12, 25, 0, 5, 300, 63, 38, 40),
        # an open order covers part: 160 − 60 − 24 = 76 → 84
        (140.0, 20, 60, 24, 12, 240, 160, 76, 84),
        # raw ≤ 0: no order
        (30.0, 5, 60, 0, 10, 400, 35, -25, 0),
        # capped at the maximum: 1000 − 10 = 990 → 1000 (pack 10) → 400
        (995.5, 4, 10, 0, 10, 400, 1000, 990, 400),
        # pack unknown → 1
        (10.2, 3, 4, 0, None, None, 14, 10, 10),
    ],
)
def test_order_quantity(fol, ss, available, open_po, pack, maximum, target, raw, order) -> None:
    result = order_quantity(fol, ss, available, open_po, pack, maximum, default_pack=1)
    assert (result.target, result.raw, result.order) == (target, raw, order)
