"""SQL that stores received logs and spans."""

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from investigator.ingest.otlp import LogRow, SpanRow


class TelemetryRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def add_spans(self, spans: list[SpanRow]) -> None:
        if not spans:
            return
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO spans (span_id, trace_id, parent_span_id, service, name, kind,"
                " start_time, end_time, status, attributes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                # A sender that got no answer sends the same spans again.
                " ON CONFLICT (span_id) DO NOTHING",
                [span._replace(attributes=Jsonb(span.attributes)) for span in spans],
            )

    def add_logs(self, logs: list[LogRow]) -> None:
        if not logs:
            return
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO logs"
                " (ts, service, level, logger, message, trace_id, span_id, attributes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [log._replace(attributes=Jsonb(log.attributes)) for log in logs],
            )
