"""The agent loop: ask the model, run the tool it asks for, repeat until it submits a report."""

import json
import re
from datetime import datetime

from pydantic import ValidationError

from investigator.agent.prompt import CONCLUDE, NUDGE, SUBMIT_DESCRIPTION, SYSTEM_PROMPT, fence
from investigator.agent.report import Evidence, Investigation, Report
from investigator.llm.types import Message, ModelClient, ModelError, ToolCall, ToolDefinition
from investigator.tools.registry import (
    ToolRegistry,
    ToolRequestError,
    describe_problems,
    simplify_schema,
    without_empty,
)

MAX_STEPS = 20
# The last steps are kept for the report: one to submit it, one to correct it.
FINAL_STEPS = 2
MAX_NUDGES = 3
MAX_RESULT_CHARS = 3000
SUBMIT = "submit_report"

_LABEL = re.compile(r"\bE\d+\b", re.IGNORECASE)


def investigate(
    description: str, reported_at: datetime, model: ModelClient, registry: ToolRegistry
) -> Investigation:
    """Investigate one incident until the model submits an acceptable report or a limit is hit."""
    submit = ToolDefinition(
        name=SUBMIT,
        description=SUBMIT_DESCRIPTION,
        input_schema=simplify_schema(Report.model_json_schema()),
    )
    tools = [*registry.definitions(), submit]
    incident = f"Reported at {reported_at:%Y-%m-%d %H:%M} (UTC).\n\n{description}"
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=incident),
    ]
    evidence: list[Evidence] = []
    already_run: dict[str, str] = {}  # a request -> the label its result was given
    nudges = 0

    def finished(status, report=None, reason=None) -> Investigation:
        return Investigation(
            status=status,
            report=report,
            failure_reason=reason,
            evidence=evidence,
            messages=messages,
        )

    for step in range(1, MAX_STEPS + 1):
        concluding = step > MAX_STEPS - FINAL_STEPS
        if step == MAX_STEPS - FINAL_STEPS + 1:
            messages.append(Message(role="user", content=CONCLUDE))
        try:
            # While concluding, only submit_report is offered, so the model has to finish.
            reply = model.complete(messages, [submit] if concluding else tools)
        except ModelError as exc:
            return finished("failed", reason=str(exc))
        messages.append(reply)

        if not reply.tool_calls:
            nudges += 1
            if nudges > MAX_NUDGES:
                return finished("failed", reason="The model stopped using its tools.")
            messages.append(Message(role="user", content=NUDGE))
            continue
        nudges = 0

        for call in reply.tool_calls:
            if call.name == SUBMIT:
                outcome = _check_report(call, evidence)
                if isinstance(outcome, Report):
                    messages.append(_answer(call, "Report accepted."))
                    return finished("resolved", report=outcome)
                messages.append(_answer(call, outcome))
            elif concluding:
                messages.append(_answer(call, f"Only {SUBMIT} can be used now."))
            else:
                messages.append(_answer(call, _gather(call, registry, evidence, already_run)))

    return finished("failed", reason="The step limit was reached without an accepted report.")


def _answer(call: ToolCall, content: str) -> Message:
    return Message(role="tool", tool_call_id=call.id, content=content)


def _gather(
    call: ToolCall, registry: ToolRegistry, evidence: list[Evidence], already_run: dict[str, str]
) -> str:
    """Run one tool request. A real result is kept as evidence and returned with its label."""
    request = f"{call.name} {json.dumps(without_empty(call.arguments), sort_keys=True)}"
    if request in already_run:
        return (
            f"You already ran this exact request. Its result is {already_run[request]}."
            f" Try something different, or call {SUBMIT}."
        )
    try:
        result = registry.run(call)
    except ToolRequestError as exc:
        return str(exc)  # a refusal is passed on, but it is not evidence and gets no label
    if len(result) > MAX_RESULT_CHARS:
        result = (
            f"{result[:MAX_RESULT_CHARS]}\n[Cut: the full result is {len(result)} characters."
            " Narrow the request to see the rest.]"
        )
    label = f"E{len(evidence) + 1}"
    already_run[request] = label
    evidence.append(Evidence(label=label, tool=call.name, arguments=call.arguments, result=result))
    return fence(result, label)


def _check_report(call: ToolCall, evidence: list[Evidence]) -> Report | str:
    """Return the report if it is acceptable, or a message saying what to correct."""
    try:
        report = Report(**without_empty(call.arguments))
    except ValidationError as exc:
        return f"The report was not valid. {describe_problems(exc)}"
    labels = [label.strip(" []").upper() for label in report.evidence]
    report = report.model_copy(update={"evidence": labels})

    gathered = [item.label for item in evidence]
    in_sentences = (
        label.upper()
        for sentence in report.rejected_hypotheses
        for label in _LABEL.findall(sentence)
    )
    missing = sorted({*labels, *in_sentences} - set(gathered))
    if missing:
        return (
            f"The report cites evidence that does not exist: {', '.join(missing)}."
            f" The evidence gathered so far is: {', '.join(gathered) or 'none'}."
        )
    return report
