"""Sends a recipe's requests to the system."""

import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import httpx

from investigator.repro.recipe import Request, Step

_TIMEOUT_S = 30.0
_REFERENCE = re.compile(r"^\$(\d+)\.(\w+)$")
_LOOKS_LIKE_REFERENCE = re.compile(r"^\$\d")


class InvalidRecipeError(Exception):
    """The recipe cannot be carried out as written."""


def run_steps(steps: list[Step], api_url: str) -> list[list[dict[str, Any]]]:
    """Send each step's requests at the same moment, one step after another.

    Returns every reply of each step, as its status and body.
    """
    replies: list[list[dict[str, Any]]] = []
    with (
        httpx.Client(base_url=api_url, timeout=_TIMEOUT_S) as http,
        ThreadPoolExecutor(max_workers=10) as pool,
    ):
        for step in steps:
            requests = [_fill_in(request, replies) for request in step.requests]
            replies.append(list(pool.map(partial(_send, http), requests)))
    return replies


def _send(http: httpx.Client, request: Request) -> dict[str, Any]:
    """Send one request. A request that fails is part of the experiment, not an error."""
    try:
        response = http.request(
            request.method, request.path, headers=request.headers, json=request.body
        )
    except httpx.HTTPError as exc:
        return {"status": None, "body": f"No reply ({type(exc).__name__})."}
    try:
        return {"status": response.status_code, "body": response.json()}
    except ValueError:
        return {"status": response.status_code, "body": response.text[:300]}


def _fill_in(request: Request, replies: list[list[dict[str, Any]]]) -> Request:
    """Replace values such as "$1.id" with fields from earlier replies."""
    if request.body is None:
        return request
    body = {name: _look_up(value, replies) for name, value in request.body.items()}
    return request.model_copy(update={"body": body})


def _look_up(value: Any, replies: list[list[dict[str, Any]]]) -> Any:
    if not isinstance(value, str) or not _LOOKS_LIKE_REFERENCE.match(value):
        return value
    match = _REFERENCE.match(value)
    if match is None:
        raise InvalidRecipeError(
            f'"{value}" is not a valid reference. Write "$1.id": a step number, a dot, and'
            " one field of that step's first reply."
        )
    step, field = int(match[1]), match[2]
    if not 1 <= step <= len(replies):
        raise InvalidRecipeError(f'"{value}" refers to a step that has not run yet.')
    reply = replies[step - 1][0]
    if not isinstance(reply["body"], dict) or field not in reply["body"]:
        raise InvalidRecipeError(
            f'"{value}" refers to a field the reply does not have. Step {step} replied with'
            f" status {reply['status']}: {str(reply['body'])[:300]}"
        )
    return reply["body"][field]
