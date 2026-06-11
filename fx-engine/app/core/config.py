"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    app_env: str = "development"
    database_url: str = "sqlite:///./fx.db"
    open_exchange_rates_app_id: str = ""
    exchange_rate_api_key: str = ""
    rate_refresh_interval_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
