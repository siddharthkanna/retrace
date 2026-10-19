"""Shared pieces for incident scenarios."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import httpx
import psycopg

API = os.environ["PAYMENT_API_URL"]
PROVIDER = os.environ["PROVIDER_URL"]
INVESTIGATOR = os.environ["INVESTIGATOR_URL"]
DATABASE = os.environ["DATABASE_URL"]
_TIMEOUT_S = 30

# The payment API keeps 4 database connections and uses them in turn, so this
# many healthy answers in a row means every broken one has been replaced.
_HEALTHY_IN_A_ROW = 6


@dataclass(frozen=True)
class IncidentReport:
    """What a scenario leaves behind for the investigator to start from."""

    description: str
    severity: str
    order_id: str


@dataclass(frozen=True)
class GroundTruth:
    """The correct answer, used only to score the investigator."""

    root_cause: str
    explanation: str
    key_evidence: tuple[str, ...]
    # What a correct root cause must say. Every group must be met; within a group, any
    # one wording is enough.
    must_name: tuple[tuple[str, ...], ...]
    # Wordings a correct root cause must not contain, such as a false cause planted for the agent.
    must_not_name: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    trigger: Callable[[], IncidentReport]
    ground_truth: GroundTruth


def set_flags(**flags: bool) -> None:
    httpx.put(f"{API}/admin/flags", json=flags).raise_for_status()


def set_provider_chaos(**chaos: float) -> None:
    httpx.put(f"{PROVIDER}/admin/chaos", json=chaos).raise_for_status()


def _run_on_database(statement: str) -> None:
    """Run one statement on the target database, the way an operator or an outage would."""
    with psycopg.connect(DATABASE, autocommit=True) as conn:
        conn.execute(statement)


def drop_database_connections() -> None:
    """Make the database close the payment API's connections, as a restart or failover does."""
    _run_on_database(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        " WHERE datname = 'payments' AND usename = 'app' AND pid <> pg_backend_pid()"
    )


def slow_refund_writes(seconds: float) -> None:
    """Make every write to the refunds table take longer, as a struggling database does."""
    _run_on_database(
        "CREATE OR REPLACE FUNCTION slow_write() RETURNS trigger LANGUAGE plpgsql"
        f" AS $$ BEGIN PERFORM pg_sleep({float(seconds)}); RETURN NEW; END $$"
    )
    _run_on_database("DROP TRIGGER IF EXISTS slow_write ON refunds")
    _run_on_database(
        "CREATE TRIGGER slow_write BEFORE INSERT ON refunds"
        " FOR EACH ROW EXECUTE FUNCTION slow_write()"
    )


def restore_database() -> None:
    """Undo slow_refund_writes."""
    _run_on_database("DROP TRIGGER IF EXISTS slow_write ON refunds")
    _run_on_database("DROP FUNCTION IF EXISTS slow_write()")


def wait_until_healthy() -> None:
    """Call the payment API until it has replaced any connections the database dropped."""
    healthy = 0
    for _ in range(50):
        healthy = healthy + 1 if httpx.get(f"{API}/health").status_code == 200 else 0
        if healthy == _HEALTHY_IN_A_ROW:
            return
    raise RuntimeError("the payment API did not recover")


def reset() -> None:
    """Return both services and the database to their healthy defaults."""
    set_flags()
    set_provider_chaos()
    restore_database()


def open_incident(report: IncidentReport) -> int:
    """File the report with the investigator and return the new incident's ID."""
    resp = httpx.post(
        f"{INVESTIGATOR}/incidents",
        json={"description": report.description, "severity": report.severity},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def new_order_id() -> str:
    return f"order-{uuid4().hex[:8]}"


def charge(order_id: str, amount_cents: int) -> httpx.Response:
    return httpx.post(
        f"{API}/charge",
        json={"order_id": order_id, "amount_cents": amount_cents},
        headers={"Idempotency-Key": str(uuid4())},
        timeout=_TIMEOUT_S,
    )


def refund(payment_id: int, amount_cents: int) -> httpx.Response:
    return httpx.post(
        f"{API}/refund",
        json={"payment_id": payment_id, "amount_cents": amount_cents},
        headers={"Idempotency-Key": str(uuid4())},
        timeout=_TIMEOUT_S,
    )
