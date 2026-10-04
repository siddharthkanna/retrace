"""Logging pieces: trace IDs on every record, JSON on stdout, rows in Postgres."""

import json
import logging
from datetime import UTC, datetime

import psycopg
from opentelemetry import trace
from psycopg.types.json import Jsonb

# Attributes every LogRecord has. Anything else was passed with `extra=`.
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "trace_id",
    "span_id",
}


def _extra_fields(record: logging.LogRecord) -> dict:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}


def _timestamp(record: logging.LogRecord) -> datetime:
    return datetime.fromtimestamp(record.created, UTC)


def _dumps(obj: object) -> str:
    return json.dumps(obj, default=str)


class TraceContextFilter(logging.Filter):
    """Stamps each record with the trace and span it was logged in."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else None
        record.span_id = format(context.span_id, "016x") if context.is_valid else None
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        return _dumps(
            {
                "ts": _timestamp(record).isoformat(),
                "service": self._service,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "trace_id": record.trace_id,
                "span_id": record.span_id,
                **_extra_fields(record),
            }
        )


class PostgresLogHandler(logging.Handler):
    def __init__(self, database_url: str, service: str) -> None:
        super().__init__()
        self._database_url = database_url
        self._service = service
        self._conn: psycopg.Connection | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._conn is None or self._conn.closed:
                self._conn = psycopg.connect(self._database_url, autocommit=True)
            self._conn.execute(
                "INSERT INTO logs"
                " (ts, service, level, logger, message, trace_id, span_id, attributes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    _timestamp(record),
                    self._service,
                    record.levelname,
                    record.name,
                    record.getMessage(),
                    record.trace_id,
                    record.span_id,
                    Jsonb(_extra_fields(record), dumps=_dumps),
                ),
            )
        except Exception:
            # Telemetry must never break the service.
            self.handleError(record)
