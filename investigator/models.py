"""Rows read from the database."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from investigator.agent.report import Evidence, Report
from investigator.enums import InvestigationStatus, Severity, Source, Status
from investigator.llm.types import Message


class Incident(BaseModel):
    # A row is a record of what is stored; it should not be edited in place.
    model_config = ConfigDict(frozen=True)

    id: int
    description: str
    severity: Severity
    status: Status
    source: Source
    created_at: datetime


class InvestigationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    incident_id: int
    model: str
    status: InvestigationStatus
    failure_reason: str | None
    report: Report | None
    evidence: list[Evidence]
    messages: list[Message]
    started_at: datetime
    finished_at: datetime | None
