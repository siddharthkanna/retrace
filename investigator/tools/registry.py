"""The one place that knows every tool: it describes them to the model and runs them."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ValidationError

from investigator.llm.types import ToolCall, ToolDefinition
from investigator.tools.code_history import (
    ListCommitsInput,
    Repo,
    ShowCommitInput,
    list_commits,
    show_commit,
)
from investigator.tools.configuration import GetConfigInput, get_config
from investigator.tools.database import DescribeDbInput, QueryDbInput, describe_db, query_db
from investigator.tools.logs import QueryLogsInput, query_logs
from investigator.tools.trace import GetTraceInput, get_trace

logger = logging.getLogger(__name__)

# Values a model sends when it means "this input is not used".
_EMPTY = (None, "", "null", "None")


class ToolRequestError(Exception):
    """A tool request could not be carried out. The message is written for the model."""


def without_empty(arguments: dict[str, Any]) -> dict[str, Any]:
    """Drop the inputs a model fills in when it means "not used"."""
    return {name: value for name, value in arguments.items() if value not in _EMPTY}


def describe_problems(exc: ValidationError) -> str:
    """Say which inputs were wrong and why, in words a model can act on."""
    return "; ".join(
        f"{'.'.join(map(str, error['loc'])) or 'inputs'}: {error['msg']}" for error in exc.errors()
    )


@dataclass(frozen=True)
class Resources:
    """Everything the tools need to reach the outside world."""

    telemetry_pool: ConnectionPool
    target_pool: ConnectionPool
    config_sources: dict[str, str]
    repo: Repo


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[Resources, Any], BaseModel]


TOOLS: tuple[Tool, ...] = (
    Tool(
        "query_logs",
        "Search the log lines written by the services. A good first step is to search for an"
        " identifier from the incident report using `contains`. Each line has a trace_id that"
        " links it to one request.",
        QueryLogsInput,
        lambda resources, request: query_logs(resources.telemetry_pool, request),
    ),
    Tool(
        "get_trace",
        "Return the full timeline of one request across all services: every timed step (span)"
        " and log line, in time order. Use a trace_id found with query_logs.",
        GetTraceInput,
        lambda resources, request: get_trace(resources.telemetry_pool, request),
    ),
    Tool(
        "describe_db",
        "List the tables of the system's database, with their columns, row counts and the"
        " links between tables. Call this before query_db.",
        DescribeDbInput,
        lambda resources, request: describe_db(resources.target_pool, request),
    ),
    Tool(
        "query_db",
        "Run one read-only SELECT statement against the system's database. Returns at most"
        " 50 rows.",
        QueryDbInput,
        lambda resources, request: query_db(resources.target_pool, request),
    ),
    Tool(
        "get_config",
        "Return the current settings of the system. To find out when a setting changed,"
        " search the logs.",
        GetConfigInput,
        lambda resources, request: get_config(resources.config_sources, request),
    ),
    Tool(
        "list_commits",
        "List recent changes to the system's code, newest first, with the files each one changed.",
        ListCommitsInput,
        lambda resources, request: list_commits(resources.repo, request),
    ),
    Tool(
        "show_commit",
        "Show the changed lines of one code change. Use an id returned by list_commits.",
        ShowCommitInput,
        lambda resources, request: show_commit(resources.repo, request),
    ),
)


class ToolRegistry:
    def __init__(self, resources: Resources, tools: Sequence[Tool] = TOOLS) -> None:
        self._resources = resources
        self._tools = {tool.name: tool for tool in tools}

    def definitions(self) -> list[ToolDefinition]:
        """The tools as they are described to the model."""
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                input_schema=simplify_schema(tool.input_model.model_json_schema()),
            )
            for tool in self._tools.values()
        ]

    def run(self, call: ToolCall) -> str:
        """Carry out one tool request and return its result as JSON.

        Raises ToolRequestError if the request can't be carried out.
        """
        tool = self._tools.get(call.name)
        if tool is None:
            raise ToolRequestError(
                f"There is no tool named '{call.name}'. The tools are: {', '.join(self._tools)}."
            )
        try:
            request = tool.input_model(**without_empty(call.arguments))
        except ValidationError as exc:
            raise ToolRequestError(f"The inputs were not valid. {describe_problems(exc)}") from exc
        try:
            result = tool.run(self._resources, request)
        except Exception as exc:
            logger.exception("tool %s failed", call.name)
            raise ToolRequestError(
                f"The tool '{call.name}' failed unexpectedly. Try a different request."
            ) from exc
        # A tool that refused, or could not answer, says so in `error`. That is not evidence.
        if getattr(result, "error", None):
            raise ToolRequestError(result.error)
        return result.model_dump_json(exclude_none=True)


def simplify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite Pydantic's description of a tool's inputs in the plainest equivalent form.

    Small models misread the nested "X or null" that Pydantic writes for an optional
    input, so only X is kept: an input that is left out is simply not used.
    """
    properties = {}
    for name, spec in schema.get("properties", {}).items():
        spec = {key: value for key, value in spec.items() if key not in ("title", "default")}
        options = [option for option in spec.pop("anyOf", []) if option != {"type": "null"}]
        if len(options) == 1:
            spec = {**options[0], **spec}
        elif options:
            spec["anyOf"] = options
        properties[name] = spec
    return {"type": "object", "properties": properties, "required": schema.get("required", [])}
