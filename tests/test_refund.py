"""End-to-end checks for refunds against the running stack."""

import os
from uuid import uuid4

import httpx

API = "http://localhost:8000"
PROVIDER = os.environ["PROVIDER_URL"]


def _charge(amount_cents: int) -> dict:
    resp = httpx.post(
        f"{API}/charge",
        json={"order_id": f"order-{uuid4()}", "amount_cents": amount_cents},
        headers={"Idempotency-Key": str(uuid4())},
    )
    return resp.json()


def _refund(payment_id: int, amount_cents: int, key: str | None = None) -> httpx.Response:
    return httpx.post(
        f"{API}/refund",
        json={"payment_id": payment_id, "amount_cents": amount_cents},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_partial_refunds_up_to_the_amount_paid():
    payment = _charge(1000)

    first = _refund(payment["id"], 400)
    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"

    assert _refund(payment["id"], 700).status_code == 409
    assert _refund(payment["id"], 600).status_code == 200


def test_same_key_refunds_only_once():
    payment, key = _charge(1000), str(uuid4())
    first = _refund(payment["id"], 400, key)
    second = _refund(payment["id"], 400, key)

    assert second.status_code == 200
    assert second.json() == first.json()
    provider_refunds = [
        r
        for r in httpx.get(f"{PROVIDER}/refunds").json()
        if r["charge_id"] == payment["provider_charge_id"]
    ]
    assert len(provider_refunds) == 1


def test_same_key_with_different_amount_is_rejected():
    payment, key = _charge(1000), str(uuid4())
    _refund(payment["id"], 400, key)
    assert _refund(payment["id"], 500, key).status_code == 422


def test_refund_of_unknown_payment_is_404():
    assert _refund(999_999_999, 100).status_code == 404
