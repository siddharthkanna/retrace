"""The report an investigation ends with, and the record of how it got there."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from investigator.agent.usage import Totals
from investigator.llm.types import Message
from investigator.repro.runner import ReproResult


class Report(BaseModel):
    """What the model submits to end an investigation."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, description="What happened, in a few sentences.")
    root_cause: str = Field(min_length=1, description="The single underlying cause.")
    evidence: list[str] = Field(
        min_length=1,
        description="Labels of the evidence that supports the root cause, such as E1 and E3.",
    )
    rejected_hypotheses: list[str] = Field(
        default=[],
        description=(
            "Other explanations you checked and ruled out. One sentence each: the"
            " explanation, why the evidence rules it out, and the label of that evidence."
            " Leave empty if you checked none."
        ),
    )
    suggested_fix: str = Field(
        min_length=1, description="What to change so this does not happen again."
    )


class Evidence(BaseModel):
    """One tool result, kept under the label the model can cite."""

    label: str
    tool: str
    arguments: dict[str, Any]
    result: str


class Attempt(BaseModel):
    """One recipe the model tried, as it wrote it, and how it went."""

    recipe: dict[str, Any]
    result: ReproResult


class Reproduction(BaseModel):
    """How the attempt to make the incident happen again went, or where it is waiting."""

    outcome: Literal["reproduced", "not_reproduced", "awaiting_approval", "running", "declined"]
    attempts: list[Attempt]
    # The recipe waiting for a person's approval, while the outcome is awaiting_approval.
    pending: dict[str, Any] | None = None


class Investigation(BaseModel):
    """Everything an investigation produced."""

    status: Literal["resolved", "failed"]
    report: Report | None = None
    failure_reason: str | None = None
    evidence: list[Evidence]
    messages: list[Message]
    reproduction: Reproduction | None = None
    usage: Totals | None = None
