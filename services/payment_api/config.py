"""Settings read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telemetry_database_url: str
    provider_url: str
    provider_timeout_s: float = 2.0
    provider_max_retries: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
