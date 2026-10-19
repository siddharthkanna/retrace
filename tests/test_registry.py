"""Checks for the tool registry: what the model is shown, and what happens to its requests."""

import json

import pytest

from investigator.llm.types import ToolCall
from investigator.tools.code_history import Repo
from investigator.tools.database import DescribeDbInput
from investigator.tools.registry import Resources, Tool, ToolRegistry, ToolRequestError

# Words that belong to the system under investigation, not to the investigator.
TARGET_SYSTEM_WORDS = ("payment", "charge", "refund", "idempotency")


@pytest.fixture(scope="module")
def resources(telemetry_pool, target_pool) -> Resources:
    return Resources(
        telemetry_pool=telemetry_pool,
        target_pool=target_pool,
        config_sources={"api": "http://api.invalid/settings"},
        repo=Repo(dir="/repo"),
    )


@pytest.fixture(scope="module")
def registry(resources) -> ToolRegistry:
    return ToolRegistry(resources)


def _run(registry: ToolRegistry, name: str, **arguments) -> str:
    return registry.run(ToolCall(id="call-1", name=name, arguments=arguments))


def _inputs(registry: ToolRegistry, tool_name: str) -> dict:
    """How one tool's inputs are described to the model."""
    return next(d for d in registry.definitions() if d.name == tool_name).input_schema


def test_all_seven_tools_are_described(registry):
    definitions = registry.definitions()

    assert [definition.name for definition in definitions] == [
        "query_logs",
        "get_trace",
        "describe_db",
        "query_db",
        "get_config",
        "list_commits",
        "show_commit",
    ]
    assert all(definition.description for definition in definitions)


def test_only_tools_for_what_is_connected_are_offered(telemetry_pool):
    registry = ToolRegistry(Resources(telemetry_pool=telemetry_pool))

    assert [definition.name for definition in registry.definitions()] == ["query_logs", "get_trace"]


def test_an_optional_input_is_described_plainly(registry):
    assert _inputs(registry, "query_logs")["properties"]["min_level"] == {
        "type": "string",
        "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "description": "Only logs at this level or more severe.",
    }
    assert "anyOf" not in json.dumps([d.input_schema for d in registry.definitions()])


def test_a_required_input_is_still_required(registry):
    assert _inputs(registry, "show_commit")["required"] == ["commit"]
    assert _inputs(registry, "query_logs")["required"] == []


def test_nothing_shown_to_the_model_names_the_target_system(registry):
    shown = json.dumps([definition.model_dump() for definition in registry.definitions()]).lower()

    for word in TARGET_SYSTEM_WORDS:
        assert word not in shown


def test_a_valid_request_returns_the_result_as_json(registry):
    result = json.loads(_run(registry, "query_db", sql="SELECT 1 AS one"))

    assert result["columns"] == ["one"]
    assert result["rows"] == [[1]]


def test_empty_fields_are_left_out_of_the_result(registry):
    result = json.loads(_run(registry, "query_db", sql="SELECT 1"))

    assert "error" not in result


@pytest.mark.parametrize("empty", ["", "null", "None", None])
def test_empty_inputs_are_ignored(registry, empty):
    reply = _run(
        registry, "query_logs", contains="no-such-text", service=empty, since=empty, min_level=empty
    )

    assert json.loads(reply) == {"logs": [], "total_matches": 0, "truncated": False}


def test_an_unknown_tool_is_refused_with_a_list_of_the_real_ones(registry):
    with pytest.raises(ToolRequestError, match="no tool named 'read_file'.*query_logs"):
        _run(registry, "read_file", path="x")


def test_invalid_inputs_are_refused_naming_each_problem(registry):
    with pytest.raises(ToolRequestError, match="inputs were not valid.*min_level.*colour"):
        _run(registry, "query_logs", min_level="bad", colour="red")


def test_a_missing_required_input_is_named(registry):
    with pytest.raises(ToolRequestError, match="commit: Field required"):
        _run(registry, "show_commit")


def test_a_tool_that_crashes_is_refused_without_the_details(resources):
    def explode(resources, request):
        raise RuntimeError("boom")

    registry = ToolRegistry(resources, [Tool("broken", "Always fails.", DescribeDbInput, explode)])

    with pytest.raises(ToolRequestError) as refusal:
        _run(registry, "broken")
    assert str(refusal.value) == "The tool 'broken' failed unexpectedly. Try a different request."


def test_a_result_that_reports_an_error_is_refused_not_returned(registry):
    with pytest.raises(ToolRequestError, match='column "nope" does not exist'):
        _run(registry, "query_db", sql="SELECT nope")
