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


# ---------------------------------------------------------------- feature 005 (T004)

ASSISTANT_DEFAULTS = {
    "gemini_model": "gemini-3.5-flash-lite",
    "gemini_base_url": None,
    "gemini_temperature": 0.0,
    "gemini_thinking_level": "low",
    "availability_offline_seconds": 30.0,
    "gemini_connect_timeout_seconds": 3.0,
    "chat_call_timeout_seconds": 10.0,
    "chat_turn_deadline_seconds": 14.0,
    "chat_max_tool_rounds": 4,
    "chat_max_tool_calls": 8,
    "chat_max_messages": 20,
    "chat_max_message_chars": 2000,
    "explanation_timeout_seconds": 8.0,
    "explanation_deadline_seconds": 9.0,
    "explanation_connect_timeout_seconds": 1.5,
    "explanation_retry_min_seconds": 3.0,
    "briefing_timeout_seconds": 45.0,
    "availability_probe_timeout_seconds": 3.0,
    "availability_cache_seconds": 30.0,
    "why_offline_memory_seconds": 30.0,
    "gemini_key_cache_seconds": 60.0,
    "briefing_top_forecasts": 3,
    "briefing_forecast_days": 7,
}


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("BRAIN_"):
            monkeypatch.delenv(key)


def test_every_assistant_setting_has_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    _clean_env(monkeypatch)
    settings = Settings()
    for name, value in ASSISTANT_DEFAULTS.items():
        assert getattr(settings, name) == value, name
    assert settings.gemini_api_key_file == Path("/run/secrets/gemini_api_key")


def test_an_empty_base_url_means_the_sdk_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("BRAIN_GEMINI_BASE_URL", "")
    assert Settings().gemini_base_url is None
    monkeypatch.setenv("BRAIN_GEMINI_BASE_URL", "http://127.0.0.1:9")
    assert Settings().gemini_base_url == "http://127.0.0.1:9"


def test_assistant_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("BRAIN_GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("BRAIN_CHAT_TURN_DEADLINE_SECONDS", "20")
    monkeypatch.setenv("BRAIN_EXPLANATION_DEADLINE_SECONDS", "9.5")
    settings = Settings()
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.chat_turn_deadline_seconds == 20
    assert settings.explanation_deadline_seconds == 9.5


@pytest.mark.parametrize(
    "field",
    [
        {"chat_call_timeout_seconds": 15, "chat_turn_deadline_seconds": 14},
        {"explanation_timeout_seconds": 10, "explanation_deadline_seconds": 9},
        {"gemini_connect_timeout_seconds": 11, "chat_call_timeout_seconds": 10},
        {"explanation_connect_timeout_seconds": 9, "explanation_timeout_seconds": 8},
        {"gemini_temperature": -1},
        {"chat_max_messages": 0},
    ],
)
def test_inconsistent_assistant_timeouts_are_refused(field: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**field)


def test_the_monotonic_clock_moves_forward() -> None:
    from brain.clock import monotonic

    first = monotonic()
    assert monotonic() >= first


@pytest.mark.parametrize(
    ("value", "expected"), [("", None), ("LOW", "low"), ("minimal", "minimal"), ("high", "high")]
)
def test_the_thinking_level(monkeypatch: pytest.MonkeyPatch, value: str, expected) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("BRAIN_GEMINI_THINKING_LEVEL", value)
    assert Settings().gemini_thinking_level == expected


def test_an_unknown_thinking_level_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(gemini_thinking_level="extreme")
