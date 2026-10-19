"""What the API accepts and returns."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from investigator.agent.report import Evidence, Report, Reproduction
from investigator.agent.usage import Totals
from investigator.enums import InvestigationStatus, Severity, Source, Status
from investigator.llm.types import Message


class IncidentCreate(BaseModel):
    """What a caller may send when opening an incident."""

    # Reject unknown fields, so nobody can try to set status or source.
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=2000)
    severity: Severity = Severity.MEDIUM


class IncidentResponse(BaseModel):
    """What the API returns for an incident."""

    # Lets the response be built directly from a database row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    severity: Severity
    status: Status
    source: Source
    created_at: datetime


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    model: str
    status: InvestigationStatus
    failure_reason: str | None
    report: Report | None
    evidence: list[Evidence]
    messages: list[Message]
    reproduction: Reproduction | None
    usage: Totals | None
    started_at: datetime
    finished_at: datetime | None
