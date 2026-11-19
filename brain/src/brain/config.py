"""Settings. Every value comes from the environment (BRAIN_* variables), never from code
(FR-034, research R-19). The README Section 4.7 defaults are the defaults here."""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_", env_parse_none_str="", extra="ignore")

    # Databases: brain-worker uses the worker login, brain-api the read-only api login. Both reach
    # only brain_db (constitution II).
    database_url: str | None = None
    api_database_url: str | None = None
    api_db_user: str | None = None  # the role the migrations grant reads to (research R-16)
    alembic_ini: Path = Path("alembic.ini")

    # The ERP's Canonical API (research R-02).
    erp_base_url: str = "http://erp-backend:8000"
    erp_service_token_file: Path = Path("/run/secrets/brain_service_token")
    erp_timeout_seconds: float = Field(default=10.0, gt=0)
    erp_jwt_public_key_file: Path = Path("/run/erp-keys/erp_jwt_ed25519.pub.pem")

    # Sales poll (README 3.2).
    poll_interval_minutes: int = Field(default=5, ge=1, le=60)
    poll_overlap_seconds: int = Field(default=120, ge=0)
    poll_history_days: int = Field(default=120, ge=91)  # 90 seeded days + today (FR-008)
    poll_page_limit: int = Field(default=500, ge=1, le=500)

    # Schedule, Africa/Cairo (README 4.1; research R-04).
    hourly_minute: int = Field(default=7, ge=0, le=59)
    end_of_day_time: str = "02:00"

    # Anomalies (README 4.7).
    anomaly_z: float = Field(default=4.0, gt=0)
    anomaly_min_history_days: int = Field(default=28, ge=2)

    # Order recommendation (README 4.7).
    review_period_days: int = Field(default=0, ge=0)
    safety_z: float = Field(default=1.65, ge=0)
    default_pack_multiple: int = Field(default=1, ge=1)
    safety_sd_window_days: int = Field(default=28, ge=2)

    # Forecasting (README 4.7; research R-07 to R-12).
    forecast_horizon_days: int = Field(default=14, ge=1)
    backtest_days: int = Field(default=28, ge=1)
    lgbm_min_history_days: int = Field(default=56, ge=1)
    lgbm_margin: float = Field(default=0.05, ge=0)
    range_low_quantile: float = Field(default=0.10, gt=0, lt=1)
    range_high_quantile: float = Field(default=0.90, gt=0, lt=1)
    degradation_factor: float = Field(default=1.5, gt=1)
    live_wape_min_days: int = Field(default=7, ge=1)
    live_wape_max_days: int = Field(default=28, ge=1)
    short_history_days: int = Field(default=7, ge=1)
    range_min_errors: int = Field(default=7, ge=1)
    artifact_keep_nights: int = Field(default=14, ge=1)
    forecasts_history_days: int = Field(default=28, ge=1)
    product_id_pattern: str = r"^P[0-9]{3,}$"  # the ERP's product IDs (brain-api)

    # LightGBM (research R-08): deterministic, one thread, fixed seed.
    lgbm_num_leaves: int = Field(default=15, ge=2)
    lgbm_min_data_in_leaf: int = Field(default=20, ge=1)
    lgbm_learning_rate: float = Field(default=0.05, gt=0)
    lgbm_num_boost_round: int = Field(default=300, ge=1)
    lgbm_seed: int = 20261202

    # The assistant (feature 005, research R-14). The key is a file, never a variable (R-11).
    # Default changed 2026-11-18 (research R-05): fastest in the live checks, right tool choice.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key_file: Path = Path("/run/secrets/gemini_api_key")
    gemini_base_url: str | None = None  # empty: Google's endpoint (the demo's offline switch)
    gemini_temperature: float = Field(default=0.0, ge=0, le=2)
    # How much the model "thinks" before answering (google-genai ThinkingConfig): minimal, low,
    # medium or high; empty sends none (the model's default). Lower is faster.
    gemini_thinking_level: str | None = "low"
    gemini_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    gemini_key_cache_seconds: float = Field(default=60.0, ge=0)
    chat_call_timeout_seconds: float = Field(default=10.0, gt=0)
    chat_turn_deadline_seconds: float = Field(default=14.0, gt=0)
    chat_max_tool_rounds: int = Field(default=4, ge=1)
    chat_max_tool_calls: int = Field(default=8, ge=1)
    chat_max_messages: int = Field(default=20, ge=1)
    chat_max_message_chars: int = Field(default=2000, ge=1)
    explanation_timeout_seconds: float = Field(default=8.0, gt=0)
    explanation_deadline_seconds: float = Field(default=9.0, gt=0)
    explanation_connect_timeout_seconds: float = Field(default=1.5, gt=0)
    explanation_retry_min_seconds: float = Field(default=3.0, ge=0)
    briefing_timeout_seconds: float = Field(default=45.0, gt=0)
    availability_probe_timeout_seconds: float = Field(default=3.0, gt=0)
    availability_cache_seconds: float = Field(default=30.0, ge=0)
    # After a real call gets 429 or a 5xx, GET /assistant says offline this long without probing
    # (models.get still answers when the quota is spent); "Check again" re-probes at once.
    availability_offline_seconds: float = Field(default=30.0, ge=0)
    why_offline_memory_seconds: float = Field(default=30.0, ge=0)
    briefing_top_forecasts: int = Field(default=3, ge=1)
    sales_top_products: int = Field(default=5, ge=1)  # the all-products sales summary
    briefing_forecast_days: int = Field(default=7, ge=1, le=14)

    @field_validator("gemini_thinking_level")
    @classmethod
    def _thinking_level(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower()
        if value not in ("minimal", "low", "medium", "high"):
            raise ValueError("must be minimal, low, medium, high or empty")
        return value

    @field_validator("end_of_day_time")
    @classmethod
    def _hh_mm(cls, value: str) -> str:
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
        if not match:
            raise ValueError("must be HH:MM, 00:00 to 23:59")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> "Settings":
        if self.range_low_quantile >= self.range_high_quantile:
            raise ValueError("range_low_quantile must be below range_high_quantile")
        if self.live_wape_min_days > self.live_wape_max_days:
            raise ValueError("live_wape_min_days must not exceed live_wape_max_days")
        if self.chat_call_timeout_seconds > self.chat_turn_deadline_seconds:
            raise ValueError("chat_call_timeout_seconds must not exceed chat_turn_deadline_seconds")
        if self.explanation_timeout_seconds > self.explanation_deadline_seconds:
            raise ValueError(
                "explanation_timeout_seconds must not exceed explanation_deadline_seconds"
            )
        if self.gemini_connect_timeout_seconds > self.chat_call_timeout_seconds:
            raise ValueError("gemini_connect_timeout_seconds must not exceed the call timeout")
        if self.explanation_connect_timeout_seconds > self.explanation_timeout_seconds:
            raise ValueError("explanation_connect_timeout_seconds must not exceed its call timeout")
        return self

    @property
    def end_of_day_hour_minute(self) -> tuple[int, int]:
        hour, minute = self.end_of_day_time.split(":")
        return int(hour), int(minute)


@lru_cache
def get_settings() -> Settings:
    return Settings()
