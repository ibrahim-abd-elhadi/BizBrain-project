"""Settings defaults and ranges (FR-034, research R-19), and the Cairo clock. Written first."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from brain.clock import today_cairo
from brain.config import Settings

DEFAULTS = {
    "poll_interval_minutes": 5,
    "poll_overlap_seconds": 120,
    "poll_history_days": 120,
    "hourly_minute": 7,
    "end_of_day_time": "02:00",
    "anomaly_z": 4.0,
    "anomaly_min_history_days": 28,
    "review_period_days": 0,
    "safety_z": 1.65,
    "default_pack_multiple": 1,
    "forecast_horizon_days": 14,
    "backtest_days": 28,
    "lgbm_min_history_days": 56,
    "lgbm_margin": 0.05,
    "range_low_quantile": 0.10,
    "range_high_quantile": 0.90,
    "degradation_factor": 1.5,
    "live_wape_min_days": 7,
    "live_wape_max_days": 28,
    "safety_sd_window_days": 28,
    "forecasts_history_days": 28,
    "short_history_days": 7,
    "range_min_errors": 7,
    "artifact_keep_nights": 14,
    "lgbm_num_leaves": 15,
    "lgbm_min_data_in_leaf": 20,
    "lgbm_learning_rate": 0.05,
    "lgbm_num_boost_round": 300,
    "lgbm_seed": 20261202,
    "erp_base_url": "http://erp-backend:8000",
}


def test_every_setting_has_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("BRAIN_"):
            monkeypatch.delenv(key)
    settings = Settings()
    for name, value in DEFAULTS.items():
        assert getattr(settings, name) == value, name


@pytest.mark.parametrize(
    "field",
    [
        {"lgbm_margin": -0.01},
        {"range_low_quantile": 0.0},
        {"range_high_quantile": 1.0},
        {"range_low_quantile": 0.9, "range_high_quantile": 0.1},
        {"hourly_minute": 60},
        {"hourly_minute": -1},
        {"poll_history_days": 90},
        {"end_of_day_time": "25:00"},
        {"anomaly_z": 0},
        {"degradation_factor": 1.0},
    ],
)
def test_out_of_range_values_are_refused(field: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**field)


def test_today_is_the_cairo_date() -> None:
    assert today_cairo(datetime(2026, 11, 17, 22, 30, tzinfo=UTC)) == date(2026, 11, 18)
    assert today_cairo(datetime(2026, 11, 17, 21, 59, tzinfo=UTC)) == date(2026, 11, 17)
