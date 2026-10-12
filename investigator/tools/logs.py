"""query_logs: search the log lines the services wrote."""

from datetime import datetime
from typing import Any, Literal

from psycopg.rows import class_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

MAX_LOGS = 50

Level = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class QueryLogsInput(BaseModel):
    """Filters for a log search. All are optional and can be combined."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, description="Only logs from this trace.")
    service: str | None = Field(default=None, description="Only logs from this service.")
    min_level: Level | None = Field(
        default=None, description="Only logs at this level or more severe."
    )
    contains: str | None = Field(
        default=None,
        min_length=1,
        description="Only logs whose message or details contain this text, ignoring case.",
    )
    since: datetime | None = Field(
        default=None, description="Only logs at or after this time (ISO 8601)."
    )
    until: datetime | None = Field(
        default=None, description="Only logs at or before this time (ISO 8601)."
    )


class LogLine(BaseModel):
    id: int
    timestamp: datetime
    service: str
    level: str
    message: str
    trace_id: str | None
    details: dict[str, Any]


class QueryLogsOutput(BaseModel):
    logs: list[LogLine]
    total_matches: int
    truncated: bool


_LEVELS: tuple[Level, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_COLUMNS = "id, ts AS timestamp, service, level, message, trace_id, attributes AS details"


def query_logs(pool: ConnectionPool, filters: QueryLogsInput) -> QueryLogsOutput:
    """Return the matching log lines, oldest first, up to MAX_LOGS."""
    conditions: list[str] = []
    params: list[Any] = []

    if filters.trace_id is not None:
        conditions.append("trace_id = %s")
        params.append(filters.trace_id)
    if filters.service is not None:
        conditions.append("service = %s")
        params.append(filters.service)
    if filters.min_level is not None:
        conditions.append("level = ANY(%s)")
        params.append(list(_LEVELS[_LEVELS.index(filters.min_level) :]))
    if filters.contains is not None:
        conditions.append(
            "(strpos(lower(message), lower(%s)) > 0"
            " OR strpos(lower(attributes::text), lower(%s)) > 0)"
        )
        params += [filters.contains, filters.contains]
    if filters.since is not None:
        conditions.append("ts >= %s")
        params.append(filters.since)
    if filters.until is not None:
        conditions.append("ts <= %s")
        params.append(filters.until)

    # Only fixed text from this file goes into the SQL; every value is a parameter.
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with pool.connection() as conn, conn.cursor(row_factory=class_row(LogLine)) as cur:
        total = conn.execute(f"SELECT count(*) FROM logs {where}", params).fetchone()[0]
        logs = cur.execute(
            f"SELECT {_COLUMNS} FROM logs {where} ORDER BY ts, id LIMIT %s",
            [*params, MAX_LOGS],
        ).fetchall()

    return QueryLogsOutput(logs=logs, total_matches=total, truncated=total > len(logs))
