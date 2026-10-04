"""End-to-end checks for charges against the running stack.

Run with: docker compose exec payment-api pytest
"""

import os
from uuid import uuid4

import httpx
import psycopg

API = "http://localhost:8000"
PROVIDER = os.environ["PROVIDER_URL"]


def _charge(order_id: str, amount_cents: int, key: str) -> httpx.Response:
    return httpx.post(
        f"{API}/charge",
        json={"order_id": order_id, "amount_cents": amount_cents},
        headers={"Idempotency-Key": key},
    )


def _provider_charges(order_id: str) -> list[dict]:
    return [c for c in httpx.get(f"{PROVIDER}/charges").json() if c["order_id"] == order_id]


def test_charge_calls_provider_and_records_payment():
    order_id = f"order-{uuid4()}"
    resp = _charge(order_id, 1250, key=str(uuid4()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT order_id, amount_cents, provider_charge_id FROM payments WHERE id = %s",
            (body["id"],),
        ).fetchone()
    assert row == (order_id, 1250, body["provider_charge_id"])


def test_same_key_charges_only_once():
    order_id, key = f"order-{uuid4()}", str(uuid4())
    first = _charge(order_id, 500, key)
    second = _charge(order_id, 500, key)

    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(_provider_charges(order_id)) == 1


def test_same_key_with_different_request_is_rejected():
    order_id, key = f"order-{uuid4()}", str(uuid4())
    _charge(order_id, 500, key)
    assert _charge(order_id, 999, key).status_code == 422


def test_charge_without_key_is_rejected():
    resp = httpx.post(f"{API}/charge", json={"order_id": "no-key", "amount_cents": 500})
    assert resp.status_code == 422


def test_charge_rejects_non_positive_amount():
    assert _charge("bad-amount", 0, key=str(uuid4())).status_code == 422
