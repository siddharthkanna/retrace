"""The report an investigation ends with, and the record of how it got there."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from investigator.llm.types import Message


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


class Investigation(BaseModel):
    """Everything an investigation produced."""

    status: Literal["resolved", "failed"]
    report: Report | None = None
    failure_reason: str | None = None
    evidence: list[Evidence]
    messages: list[Message]
