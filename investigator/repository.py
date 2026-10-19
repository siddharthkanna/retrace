"""SQL for the incidents and investigations tables."""

import psycopg
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from investigator.agent.report import Investigation
from investigator.enums import Severity, Source
from investigator.models import Incident, InvestigationRecord

_COLUMNS = "id, description, severity, status, source, created_at"


class IncidentRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def create(self, description: str, severity: Severity, source: Source) -> Incident:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Incident)) as cur:
            return cur.execute(
                "INSERT INTO incidents (description, severity, source)"
                f" VALUES (%s, %s, %s) RETURNING {_COLUMNS}",
                (description, severity, source),
            ).fetchone()

    def get(self, incident_id: int) -> Incident | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Incident)) as cur:
            return cur.execute(
                f"SELECT {_COLUMNS} FROM incidents WHERE id = %s", (incident_id,)
            ).fetchone()

    def list(self, limit: int = 50) -> list[Incident]:
        """Return the newest incidents first."""
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Incident)) as cur:
            return cur.execute(
                f"SELECT {_COLUMNS} FROM incidents ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()


_INVESTIGATION_COLUMNS = (
    "id, incident_id, model, status, failure_reason, report, evidence, messages,"
    " reproduction, usage, started_at, finished_at"
)
_INTERRUPTED = "The service restarted during the investigation."


class InvestigationAlreadyRunningError(Exception):
    """This incident already has an investigation in progress."""


class InvestigationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def start(self, incident_id: int, model: str) -> InvestigationRecord:
        """Record that an investigation has begun and mark its incident as being investigated."""
        try:
            with self._pool.connection() as conn, self._cursor(conn) as cur:
                record = cur.execute(
                    "INSERT INTO investigations (incident_id, model) VALUES (%s, %s)"
                    f" RETURNING {_INVESTIGATION_COLUMNS}",
                    (incident_id, model),
                ).fetchone()
                conn.execute(
                    "UPDATE incidents SET status = 'investigating' WHERE id = %s", (incident_id,)
                )
        except psycopg.errors.UniqueViolation as exc:
            raise InvestigationAlreadyRunningError(incident_id) from exc
        return record

    def finish(self, investigation_id: int, result: Investigation) -> InvestigationRecord:
        """Store the outcome and give the incident the same status."""
        report = Jsonb(result.report.model_dump()) if result.report else None
        reproduction = Jsonb(result.reproduction.model_dump()) if result.reproduction else None
        usage = Jsonb(result.usage.model_dump()) if result.usage else None
        with self._pool.connection() as conn, self._cursor(conn) as cur:
            record = cur.execute(
                "UPDATE investigations SET status = %s, failure_reason = %s, report = %s,"
                " evidence = %s, messages = %s, reproduction = %s, usage = %s, finished_at = now()"
                f" WHERE id = %s RETURNING {_INVESTIGATION_COLUMNS}",
                (
                    result.status,
                    result.failure_reason,
                    report,
                    Jsonb([item.model_dump() for item in result.evidence]),
                    Jsonb([message.model_dump() for message in result.messages]),
                    reproduction,
                    usage,
                    investigation_id,
                ),
            ).fetchone()
            conn.execute(
                "UPDATE incidents SET status = %s WHERE id = %s",
                (result.status, record.incident_id),
            )
        return record

    def approve(self, investigation_id: int) -> InvestigationRecord | None:
        """Mark a waiting recipe as approved and running. None if nothing was waiting."""
        return self._settle(investigation_id, "running")

    def decline(self, investigation_id: int) -> InvestigationRecord | None:
        """End a reproduction whose recipe was declined. None if nothing was waiting."""
        return self._settle(investigation_id, "declined")

    def _settle(self, investigation_id: int, outcome: str) -> InvestigationRecord | None:
        # The condition makes this happen once, however many times the button is pressed.
        with self._pool.connection() as conn, self._cursor(conn) as cur:
            return cur.execute(
                "UPDATE investigations SET reproduction = reproduction || %s"
                " WHERE id = %s AND reproduction->>'outcome' = 'awaiting_approval'"
                f" RETURNING {_INVESTIGATION_COLUMNS}",
                (Jsonb({"outcome": outcome}), investigation_id),
            ).fetchone()

    def list_for(self, incident_id: int) -> list[InvestigationRecord]:
        """Every investigation of one incident, newest first."""
        with self._pool.connection() as conn, self._cursor(conn) as cur:
            return cur.execute(
                f"SELECT {_INVESTIGATION_COLUMNS} FROM investigations"
                " WHERE incident_id = %s ORDER BY id DESC",
                (incident_id,),
            ).fetchall()

    def fail_interrupted(self) -> int:
        """Close investigations that a stopped service left running. Returns how many."""
        with self._pool.connection() as conn:
            incident_ids = [
                row[0]
                for row in conn.execute(
                    "UPDATE investigations SET status = 'failed', failure_reason = %s,"
                    " finished_at = now() WHERE status = 'running' RETURNING incident_id",
                    (_INTERRUPTED,),
                )
            ]
            conn.execute(
                "UPDATE incidents SET status = 'failed' WHERE id = ANY(%s)", (incident_ids,)
            )
            # An approved recipe was being carried out; the report itself is kept.
            conn.execute(
                "UPDATE investigations SET reproduction = reproduction || %s"
                " WHERE reproduction->>'outcome' = 'running'",
                (Jsonb({"outcome": "not_reproduced", "pending": None}),),
            )
        return len(incident_ids)

    @staticmethod
    def _cursor(conn: psycopg.Connection) -> psycopg.Cursor[InvestigationRecord]:
        return conn.cursor(row_factory=class_row(InvestigationRecord))
