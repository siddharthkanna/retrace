"""Checks for the reproduction phase, driven by a scripted model against the real test-bed."""

import os
from uuid import uuid4

import pytest

from investigator.agent.report import Investigation, Report
from investigator.agent.reproduce import MAX_ATTEMPTS, RUN_REPRO, reproduce
from investigator.llm.types import Message, ToolCall
from investigator.repro.recipe import Recipe
from investigator.repro.runner import Target
from investigator.tools.code_history import Repo
from investigator.tools.registry import Resources, ToolRegistry, simplify_schema
from scenarios.base import slow_refund_writes
from tests.helpers import ScriptedModel, ask

API = os.environ["PAYMENT_API_URL"]
SOURCES = {"payment-api": f"{API}/admin/flags"}
REPORT = Report(summary="It broke.", root_cause="A bug.", evidence=["E1"], suggested_fix="Fix.")


@pytest.fixture
def registry(telemetry_pool, target_pool) -> ToolRegistry:
    resources = Resources(
        telemetry_pool=telemetry_pool,
        target_pool=target_pool,
        config_sources=SOURCES,
        repo=Repo(),
    )
    return ToolRegistry(resources)


@pytest.fixture
def target(target_pool) -> Target:
    return Target(api_url=API, config_sources=SOURCES, pool=target_pool)


def _resolved() -> Investigation:
    messages = [Message(role="user", content="Something broke.")]
    return Investigation(status="resolved", report=REPORT, evidence=[], messages=messages)


def _post(path: str, **body) -> dict:
    headers = {"Idempotency-Key": str(uuid4())}
    return {"method": "POST", "path": path, "headers": headers, "body": body}


def _double_refund(**fields) -> dict:
    """A recipe that refunds one new payment in full twice at the same moment."""
    order_id = f"order-{uuid4().hex[:8]}"
    refund = {"payment_id": "$1.id", "amount_cents": 3000}
    return {
        "settings": {"payment-api": {"refund_row_locking": False}},
        "steps": [
            {"requests": [_post("/charge", order_id=order_id, amount_cents=3000)]},
            {"requests": [_post("/refund", **refund), _post("/refund", **refund)]},
        ],
        "check_sql": (
            "SELECT 1 FROM refunds r JOIN payments p ON p.id = r.payment_id"
            f" WHERE p.order_id = '{order_id}'"
            " GROUP BY p.id HAVING sum(r.amount_cents) > p.amount_cents"
        ),
        **fields,
    }


def test_a_working_recipe_is_recorded_as_reproduced_and_the_report_is_untouched(registry, target):
    slow_refund_writes(0.3)
    model = ScriptedModel(ask(RUN_REPRO, **_double_refund()))

    investigation = reproduce(_resolved(), model, registry, target)

    assert investigation.reproduction.outcome == "reproduced"
    assert len(investigation.reproduction.attempts) == 1
    assert investigation.report == REPORT
    assert model.offered == [["describe_db", "query_db", RUN_REPRO]]


def test_a_badly_shaped_recipe_counts_as_an_attempt_and_says_what_to_fix(registry, target):
    model = ScriptedModel(ask(RUN_REPRO, steps=[]), ask("describe_db"), Message(role="assistant"))

    investigation = reproduce(_resolved(), model, registry, target)

    (attempt,) = investigation.reproduction.attempts
    assert investigation.reproduction.outcome == "not_reproduced"
    assert attempt.result.outcome == "invalid_recipe"
    assert "steps" in attempt.result.detail


def test_the_model_gets_no_more_than_the_allowed_attempts(registry, target):
    # With row locking left on, the second refund is refused, so nothing is reproduced.
    harmless = [ask(RUN_REPRO, **_double_refund(settings={})) for _ in range(MAX_ATTEMPTS + 1)]

    investigation = reproduce(_resolved(), ScriptedModel(*harmless), registry, target)

    assert investigation.reproduction.outcome == "not_reproduced"
    assert len(investigation.reproduction.attempts) == MAX_ATTEMPTS


def test_nested_shapes_are_described_to_the_model_in_full():
    schema = simplify_schema(Recipe.model_json_schema())

    request = schema["properties"]["steps"]["items"]["properties"]["requests"]["items"]
    assert "path" in request["properties"]
    assert "$ref" not in str(schema)


def test_the_model_is_shown_the_description_of_the_api(registry, target):
    model = ScriptedModel(Message(role="assistant"))

    investigation = reproduce(_resolved(), model, registry, target)

    assert "/refund" in investigation.messages[1].content


def test_a_recipe_that_could_not_be_carried_out_is_not_counted(registry, target):
    already_true = [ask(RUN_REPRO, **_double_refund(check_sql="SELECT 1"))] * (MAX_ATTEMPTS + 1)
    model = ScriptedModel(*already_true, Message(role="assistant"))

    investigation = reproduce(_resolved(), model, registry, target)

    assert len(investigation.reproduction.attempts) == MAX_ATTEMPTS + 1


def test_only_a_recipe_that_can_be_carried_out_waits_for_approval(registry, target):
    recipe = _double_refund()
    model = ScriptedModel(ask(RUN_REPRO, steps=[]), ask(RUN_REPRO, **recipe))

    waiting = reproduce(_resolved(), model, registry, target, ask_first=True)

    assert waiting.reproduction.outcome == "awaiting_approval"
    assert waiting.reproduction.pending == recipe
    assert [a.result.outcome for a in waiting.reproduction.attempts] == ["invalid_recipe"]


def test_an_approved_recipe_is_carried_out_and_the_conversation_continues(registry, target):
    slow_refund_writes(0.3)
    model = ScriptedModel(ask(RUN_REPRO, **_double_refund()))
    waiting = reproduce(_resolved(), model, registry, target, ask_first=True)
    approved = waiting.model_copy(
        update={"reproduction": waiting.reproduction.model_copy(update={"outcome": "running"})}
    )

    investigation = reproduce(approved, model, registry, target, ask_first=True)

    assert investigation.reproduction.outcome == "reproduced"
    assert investigation.messages[-1].role == "tool"
    assert len(model.offered) == 1  # carrying out the approved recipe needed no new model call


def test_a_lookup_in_the_same_reply_is_answered_once_across_the_pause(registry, target):
    slow_refund_writes(0.3)
    lookup = ToolCall(id="a", name="query_db", arguments={"sql": "SELECT 1"})
    recipe = ToolCall(id="b", name=RUN_REPRO, arguments=_double_refund())
    model = ScriptedModel(Message(role="assistant", tool_calls=[lookup, recipe]))
    waiting = reproduce(_resolved(), model, registry, target, ask_first=True)
    approved = waiting.model_copy(
        update={"reproduction": waiting.reproduction.model_copy(update={"outcome": "running"})}
    )

    investigation = reproduce(approved, model, registry, target, ask_first=True)

    answers = [m.tool_call_id for m in investigation.messages if m.role == "tool"]
    assert answers == ["a", "b"]
    assert investigation.reproduction.outcome == "reproduced"
