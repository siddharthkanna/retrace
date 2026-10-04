"""Writes finished OpenTelemetry spans to the telemetry database."""

from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from psycopg.types.json import Jsonb

_INSERT = (
    "INSERT INTO spans (span_id, trace_id, parent_span_id, service, name, kind,"
    " start_time, end_time, status, attributes)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


class PostgresSpanExporter(SpanExporter):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn: psycopg.Connection | None = None

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            if self._conn is None or self._conn.closed:
                self._conn = psycopg.connect(self._database_url, autocommit=True)
            with self._conn.cursor() as cur:
                cur.executemany(_INSERT, [_to_row(span) for span in spans])
        except psycopg.Error:
            # Telemetry must never break the service; the SDK logs the failure.
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        if self._conn is not None:
            self._conn.close()


def _to_row(span: ReadableSpan) -> tuple:
    context = span.get_span_context()
    return (
        format(context.span_id, "016x"),
        format(context.trace_id, "032x"),
        format(span.parent.span_id, "016x") if span.parent else None,
        span.resource.attributes["service.name"],
        span.name,
        span.kind.name,
        _from_nanoseconds(span.start_time),
        _from_nanoseconds(span.end_time),
        span.status.status_code.name,
        Jsonb(dict(span.attributes)),
    )


def _from_nanoseconds(timestamp_ns: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ns / 1e9, UTC)
