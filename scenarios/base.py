"""Shared pieces for incident scenarios."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import httpx

API = os.environ.get("PAYMENT_API_URL", "http://localhost:8000")
PROVIDER = os.environ["PROVIDER_URL"]
_TIMEOUT_S = 30


@dataclass(frozen=True)
class Incident:
    """What a scenario leaves behind for the investigator to start from."""

    report: str
    order_id: str


@dataclass(frozen=True)
class GroundTruth:
    """The correct answer, used only to score the investigator."""

    root_cause: str
    explanation: str
    key_evidence: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    id: str
    trigger: Callable[[], Incident]
    ground_truth: GroundTruth


def set_flags(**flags: bool) -> None:
    httpx.put(f"{API}/admin/flags", json=flags).raise_for_status()


def set_payment_chaos(**chaos: bool | int) -> None:
    httpx.put(f"{API}/admin/chaos", json=chaos).raise_for_status()


def set_provider_chaos(**chaos: float) -> None:
    httpx.put(f"{PROVIDER}/admin/chaos", json=chaos).raise_for_status()


def reset() -> None:
    """Return both services to their healthy defaults."""
    set_flags()
    set_payment_chaos()
    set_provider_chaos()


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
