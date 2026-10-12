"""Checks that a request leaves a trace and logs behind."""

import os
import time
from uuid import uuid4

import httpx
import psycopg

API = os.environ["PAYMENT_API_URL"]


def _query(sql: str, params: tuple) -> list[tuple]:
    with psycopg.connect(os.environ["TELEMETRY_DATABASE_URL"]) as conn:
        return conn.execute(sql, params).fetchall()


def _wait_for_rows(sql: str, params: tuple, timeout_s: float = 5.0) -> list[tuple]:
    """Telemetry is written in the background, so poll until it arrives."""
    deadline = time.monotonic() + timeout_s
    while True:
        rows = _query(sql, params)
        if rows or time.monotonic() > deadline:
            return rows
        time.sleep(0.2)


def test_charge_leaves_one_trace_across_both_services():
    order_id = f"order-{uuid4()}"
    httpx.post(
        f"{API}/charge",
        json={"order_id": order_id, "amount_cents": 500},
        headers={"Idempotency-Key": str(uuid4())},
    )

    logs = _wait_for_rows(
        "SELECT trace_id FROM logs"
        " WHERE message = 'payment recorded' AND attributes->>'order_id' = %s",
        (order_id,),
    )
    assert len(logs) == 1
    trace_id = logs[0][0]
    assert trace_id is not None

    spans = _wait_for_rows(
        "SELECT DISTINCT service FROM spans WHERE trace_id = %s AND service = 'provider-mock'",
        (trace_id,),
    )
    assert spans, "the provider's spans should join the payment API's trace"

    provider_logs = _query(
        "SELECT message FROM logs WHERE trace_id = %s AND service = 'provider-mock'",
        (trace_id,),
    )
    assert ("charge created",) in provider_logs


def test_a_rejected_request_is_logged_with_its_reason():
    resp = httpx.post(
        f"{API}/refund",
        json={"payment_id": 999_999_999, "amount_cents": 100},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert resp.status_code == 404

    logs = _wait_for_rows(
        "SELECT level, attributes->>'reason' FROM logs"
        " WHERE message = 'request rejected' AND attributes->>'path' = %s"
        " ORDER BY ts DESC LIMIT 1",
        ("/refund",),
    )
    assert logs == [("WARNING", "payment not found")]
