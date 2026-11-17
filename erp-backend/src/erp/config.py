"""Settings. Every value comes from the environment (docker-compose / .env), never from code."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # An empty value (for example ERP_RANDOM_SEED= in .env.example) reads as None.
    model_config = SettingsConfigDict(env_parse_none_str="", extra="ignore")

    # Required.
    erp_database_url: str
    erp_jwt_private_key_file: Path

    # Token lifetime in minutes (research R-11).
    erp_jwt_ttl_minutes: int = Field(default=480, gt=0)

    # The single manager account created by `python -m erp.seed` (FR-010).
    erp_manager_username: str | None = None
    erp_manager_password: SecretStr | None = None

    # Simulate Sales (FR-011, FR-012, research R-15 and R-16).
    erp_spike_z: float = Field(default=4.0, gt=0)
    erp_simulate_batch_fraction: float = Field(default=0.25, gt=0, le=1)
    erp_simulate_return_rate: float = Field(default=0.02, ge=0, lt=1)
    erp_random_seed: int | None = None

    # Seed generator: a fixed seed makes every reseed identical (research R-17).
    erp_seed_random_seed: int = 20261202


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
