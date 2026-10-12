"""Checks for the agent loop, driven by a scripted model in place of a real one."""

from datetime import UTC, datetime

import pytest

from investigator.agent.loop import (
    FINAL_STEPS,
    MAX_NUDGES,
    MAX_RESULT_CHARS,
    MAX_STEPS,
    SUBMIT,
    investigate,
)
from investigator.agent.prompt import CONCLUDE, NUDGE
from investigator.agent.report import Investigation
from investigator.llm.types import Message, ModelError
from investigator.tools.code_history import Repo
from investigator.tools.registry import Resources, ToolRegistry
from tests.helpers import ScriptedModel, ask, say, select, submit

REPORTED_AT = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry(telemetry_pool, target_pool) -> ToolRegistry:
    resources = Resources(
        telemetry_pool=telemetry_pool, target_pool=target_pool, config_sources={}, repo=Repo()
    )
    return ToolRegistry(resources)


def run(
    registry: ToolRegistry, *replies: Message | Exception
) -> tuple[Investigation, ScriptedModel]:
    model = ScriptedModel(*replies)
    return investigate("Something broke.", REPORTED_AT, model, registry), model


def told(investigation: Investigation) -> list[str]:
    """Everything the loop said back to the model, in order."""
    return [m.content for m in investigation.messages[2:] if m.role in ("tool", "user")]


def test_tools_are_run_and_labelled_until_a_report_is_accepted(registry):
    investigation, _ = run(registry, select(), ask("describe_db"), submit("E1", "E2"))

    assert investigation.status == "resolved"
    assert investigation.report.root_cause == "A bug."
    assert [(item.label, item.tool) for item in investigation.evidence] == [
        ("E1", "query_db"),
        ("E2", "describe_db"),
    ]
    assert told(investigation)[0].startswith("[E1] ")
    assert told(investigation)[-1] == "Report accepted."


def test_the_incident_message_carries_the_reported_time(registry):
    investigation, _ = run(registry, select(), submit("E1"))

    assert investigation.messages[1].content == (
        "Reported at 2026-10-11 09:30 (UTC).\n\nSomething broke."
    )


def test_labels_in_a_report_are_tidied(registry):
    investigation, _ = run(registry, select(), submit("[e1]"))

    assert investigation.status == "resolved"
    assert investigation.report.evidence == ["E1"]


def test_a_plain_text_reply_gets_a_nudge_and_the_work_continues(registry):
    investigation, _ = run(registry, say("Let me think."), select(), submit("E1"))

    assert investigation.status == "resolved"
    assert told(investigation)[0] == NUDGE


def test_too_many_plain_text_replies_in_a_row_end_it_as_failed(registry):
    investigation, _ = run(registry, *[say("Hmm.")] * (MAX_NUDGES + 1))

    assert investigation.status == "failed"
    assert investigation.failure_reason == "The model stopped using its tools."


def test_refused_requests_are_passed_on_but_are_not_evidence(registry):
    investigation, _ = run(
        registry,
        ask("query_db", sql="DELETE FROM payments"),
        ask("read_file", path="x"),
        ask("query_logs", min_level="bad"),
        select(),
        submit("E1"),
    )

    assert told(investigation)[0] == "Only a single SELECT statement is allowed."
    assert "no tool named 'read_file'" in told(investigation)[1]
    assert "inputs were not valid" in told(investigation)[2]
    assert [item.label for item in investigation.evidence] == ["E1"]


def test_an_exact_repeat_is_not_run_again(registry):
    investigation, _ = run(registry, select(1), select(1), submit("E1"))

    assert [item.label for item in investigation.evidence] == ["E1"]
    assert "already ran this exact request. Its result is [E1]" in told(investigation)[1]


def test_a_report_citing_missing_evidence_is_rejected_and_can_be_corrected(registry):
    investigation, _ = run(registry, select(), submit("E1", "E7"), submit("E1"))

    assert investigation.status == "resolved"
    assert told(investigation)[1] == (
        "The report cites evidence that does not exist: E7. The evidence gathered so far is: E1."
    )


def test_labels_inside_rejected_hypotheses_are_checked_too(registry):
    investigation, _ = run(
        registry,
        select(),
        submit("E1", rejected_hypotheses=["A setting: ruled out by e5."]),
        submit("E1", rejected_hypotheses=["A setting: ruled out by E1."]),
    )

    assert "does not exist: E5" in told(investigation)[1]
    assert investigation.report.rejected_hypotheses == ["A setting: ruled out by E1."]


def test_a_report_with_no_evidence_is_rejected(registry):
    investigation, _ = run(registry, select(), submit(), submit("E1"))

    assert told(investigation)[1].startswith("The report was not valid. evidence")
    assert investigation.status == "resolved"


def test_in_the_final_steps_only_the_report_can_be_submitted(registry):
    investigation, model = run(registry, *[select(n) for n in range(MAX_STEPS)])

    assert len(model.offered[MAX_STEPS - FINAL_STEPS - 1]) > 1
    assert model.offered[-FINAL_STEPS:] == [[SUBMIT]] * FINAL_STEPS
    assert CONCLUDE in told(investigation)
    assert told(investigation)[-1] == f"Only {SUBMIT} can be used now."


def test_a_report_rejected_in_the_final_steps_can_still_be_corrected(registry):
    searching = [select(n) for n in range(MAX_STEPS - FINAL_STEPS)]

    investigation, _ = run(registry, *searching, submit("E99"), submit("E2"))

    assert investigation.status == "resolved"


def test_running_out_of_steps_ends_it_as_failed(registry):
    investigation, model = run(registry, *[select(n) for n in range(MAX_STEPS)])

    assert investigation.status == "failed"
    assert investigation.failure_reason == "The step limit was reached without an accepted report."
    assert len(model.offered) == MAX_STEPS


def test_an_unreachable_model_ends_it_as_failed_but_keeps_the_evidence(registry):
    outage = ModelError("The model could not be reached (ConnectError).")

    investigation, _ = run(registry, select(), outage)

    assert investigation.status == "failed"
    assert investigation.failure_reason == "The model could not be reached (ConnectError)."
    assert [item.label for item in investigation.evidence] == ["E1"]


def test_an_oversized_result_is_cut_with_a_note(registry):
    big = ask("query_db", sql="SELECT repeat('x', 300) FROM generate_series(1, 50)")

    investigation, _ = run(registry, big, submit("E1"))

    result = investigation.evidence[0].result
    assert len(result) < MAX_RESULT_CHARS + 200
    assert "Cut: the full result is" in result
