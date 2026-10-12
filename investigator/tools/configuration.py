"""get_config: read the current settings of the system being investigated."""

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


class GetConfigInput(BaseModel):
    """get_config takes no input."""

    model_config = ConfigDict(extra="forbid")


class SourceConfig(BaseModel):
    source: str
    values: dict[str, Any] | None = None
    # Set instead of values when the source could not be read.
    error: str | None = None


class GetConfigOutput(BaseModel):
    sources: list[SourceConfig]


_TIMEOUT_S = 5.0


def get_config(sources: dict[str, str], request: GetConfigInput) -> GetConfigOutput:
    """Read the current settings from every configured source."""
    return GetConfigOutput(sources=[_read(name, url) for name, url in sources.items()])


def _read(name: str, url: str) -> SourceConfig:
    try:
        response = httpx.get(url, timeout=_TIMEOUT_S)
        response.raise_for_status()
        values = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return SourceConfig(source=name, error=f"{type(exc).__name__}: {exc}")
    if not isinstance(values, dict):
        return SourceConfig(source=name, error="the source did not return named settings")
    return SourceConfig(source=name, values=values)
