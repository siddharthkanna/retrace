"""Settings read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    # Read-only logins. The investigator can look at evidence but never change it.
    telemetry_database_url: str
    target_database_url: str
    # Where to read the target system's current settings from: name -> address.
    config_sources: dict[str, str] = {}
    # The target system's code history. With no folder set, the agent has none to look at.
    target_repo_dir: str | None = None
    # Only these folders and files are ever shown.
    target_repo_paths: list[str] = []
    # Files hidden even inside the allowed folders.
    target_repo_exclude: list[str] = []
    # Only changes made after this commit are shown.
    target_repo_baseline: str | None = None
    # The model that runs investigations.
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
