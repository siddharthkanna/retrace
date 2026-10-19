"""Carries out a recipe and reports whether the incident happened again."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from investigator.repro.recipe import Recipe
from investigator.repro.steps import InvalidRecipeError, run_steps
from investigator.tools.database import QueryDbInput, query_db

_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Target:
    """The system a recipe is carried out against: a test or staging copy, never production."""

    api_url: str
    config_sources: dict[str, str]
    pool: ConnectionPool


class ReproResult(BaseModel):
    outcome: Literal["reproduced", "not_reproduced", "invalid_recipe"]
    detail: str
    # What each request of each step returned, so a recipe that went wrong can be corrected.
    replies: list[list[str]] = []


def run_recipe(recipe: Recipe, target: Target) -> ReproResult:
    try:
        if _incident_shows(recipe, target):
            raise InvalidRecipeError(
                "The check returns rows before the steps have run, so it cannot show that"
                " the steps caused anything. Make it match only what the steps create."
            )
        with _settings_changed(recipe.settings, target.config_sources):
            replies = run_steps(recipe.steps, target.api_url)
        happened = _incident_shows(recipe, target)
    except InvalidRecipeError as exc:
        return ReproResult(outcome="invalid_recipe", detail=str(exc))
    shown = [[f"{r['status']}: {str(r['body'])[:300]}" for r in step] for step in replies]
    if happened:
        detail = "The check returned no rows before the steps and at least one row after them."
        return ReproResult(outcome="reproduced", detail=detail, replies=shown)
    detail = "The check returned no rows after the steps."
    return ReproResult(outcome="not_reproduced", detail=detail, replies=shown)


def _incident_shows(recipe: Recipe, target: Target) -> bool:
    result = query_db(target.pool, QueryDbInput(sql=recipe.check_sql))
    if result.error:
        raise InvalidRecipeError(f"The check could not be run: {result.error}")
    return result.row_count > 0


@contextmanager
def _settings_changed(
    changes: dict[str, dict[str, Any]], sources: dict[str, str]
) -> Iterator[None]:
    """Apply the recipe's settings, and put the old ones back afterwards whatever happens."""
    before = {name: _read(name, sources) for name in changes}
    for name, values in changes.items():
        if unknown := values.keys() - before[name].keys():
            raise InvalidRecipeError(f"{name} has no setting named {sorted(unknown)}.")
    try:
        for name, values in changes.items():
            _write(sources[name], {**before[name], **values})
        yield
    finally:
        for name, values in before.items():
            _write(sources[name], values)


def _read(name: str, sources: dict[str, str]) -> dict[str, Any]:
    if name not in sources:
        raise InvalidRecipeError(f"There is no settings source named {name}.")
    response = httpx.get(sources[name], timeout=_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _write(url: str, values: dict[str, Any]) -> None:
    response = httpx.put(url, json=values, timeout=_TIMEOUT_S)
    if response.is_client_error:
        raise InvalidRecipeError(f"The system refused the settings: {response.text[:200]}")
    response.raise_for_status()
