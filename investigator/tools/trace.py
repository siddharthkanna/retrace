"""get_trace: the full story of one request, across every service."""

from datetime import datetime
from typing import Any, Literal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

MAX_ENTRIES = 200


class GetTraceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, description="The trace to return, as found on a log line.")


class TimelineEntry(BaseModel):
    """One span or one log line."""

    type: Literal["span", "log"]
    timestamp: datetime
    service: str
    summary: str
    duration_ms: float | None = None
    status: str | None = None
    level: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    details: dict[str, Any]


class GetTraceOutput(BaseModel):
    trace_id: str
    found: bool
    started_at: datetime | None
    duration_ms: float | None
    services: list[str]
    timeline: list[TimelineEntry]
    truncated: bool


def get_trace(pool: ConnectionPool, request: GetTraceInput) -> GetTraceOutput:
    """Return every span and log line of one trace, merged in time order."""
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        spans = cur.execute(
            "SELECT span_id, parent_span_id, service, name, kind, start_time, end_time,"
            " status, attributes"
            " FROM spans WHERE trace_id = %s ORDER BY start_time LIMIT %s",
            (request.trace_id, MAX_ENTRIES + 1),
        ).fetchall()
        logs = cur.execute(
            "SELECT span_id, service, level, message, ts, attributes"
            " FROM logs WHERE trace_id = %s ORDER BY ts, id LIMIT %s",
            (request.trace_id, MAX_ENTRIES + 1),
        ).fetchall()

    entries = [_span_entry(row) for row in spans] + [_log_entry(row) for row in logs]
    # Time order. On a tie, a span goes before a log line written inside it.
    entries.sort(key=lambda entry: (entry.timestamp, entry.type != "span"))

    return GetTraceOutput(
        trace_id=request.trace_id,
        found=bool(entries),
        started_at=entries[0].timestamp if entries else None,
        duration_ms=_milliseconds(
            min(row["start_time"] for row in spans), max(row["end_time"] for row in spans)
        )
        if spans
        else None,
        services=sorted({entry.service for entry in entries}),
        timeline=entries[:MAX_ENTRIES],
        truncated=len(entries) > MAX_ENTRIES,
    )


def _span_entry(row: dict[str, Any]) -> TimelineEntry:
    return TimelineEntry(
        type="span",
        timestamp=row["start_time"],
        service=row["service"],
        summary=row["name"],
        duration_ms=_milliseconds(row["start_time"], row["end_time"]),
        status=row["status"],
        span_id=row["span_id"],
        parent_span_id=row["parent_span_id"],
        details={"kind": row["kind"], **row["attributes"]},
    )


def _log_entry(row: dict[str, Any]) -> TimelineEntry:
    return TimelineEntry(
        type="log",
        timestamp=row["ts"],
        service=row["service"],
        summary=row["message"],
        level=row["level"],
        span_id=row["span_id"],
        details=row["attributes"],
    )


def _milliseconds(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() * 1000, 3)
