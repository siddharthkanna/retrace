"""Settings read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # A setting left empty counts as not set.
    model_config = SettingsConfigDict(env_ignore_empty=True)

    database_url: str
    # Where the logs and traces are kept: one login to read them, one to store new ones.
    telemetry_database_url: str
    telemetry_ingest_database_url: str
    # Everything about the target system is optional: the agent works with what is connected.
    # Its database. Any login will do: the investigator only ever opens it read-only.
    target_database_url: str | None = None
    # Where to read the target system's current settings from: name -> address.
    config_sources: dict[str, str] = {}
    # The target system's code history. With no folder set, the agent has none to look at.
    target_repo_dir: str | None = None
    # Only these folders and files are ever shown. Left empty, all of it may be shown.
    target_repo_paths: list[str] = []
    # Files hidden even inside the allowed folders.
    target_repo_exclude: list[str] = []
    # Only changes made after this commit are shown.
    target_repo_baseline: str | None = None
    # Where recipes are carried out: a test or staging copy, never production.
    # Left unset, investigations end at the report.
    target_api_url: str | None = None
    # Each recipe waits for a person to approve it before requests are sent to the system.
    reproduction_needs_approval: bool = True
    # The model that runs investigations.
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None = None
    # The header the key is sent in. Left unset, it is sent as a bearer token.
    llm_api_key_header: str | None = None
    # US dollars per million tokens. Left unset, the cost of an investigation is not shown.
    llm_price_input_per_million: float | None = None
    llm_price_output_per_million: float | None = None
    # Where to send traces of the agent's own work, in OpenTelemetry's format: a full
    # OTLP/HTTP address ending in /v1/traces. Left unset, they are not sent anywhere.
    agent_traces_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
