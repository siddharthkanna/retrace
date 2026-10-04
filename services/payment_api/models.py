"""Rows read from the database."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Payment:
    id: int
    order_id: str
    amount_cents: int
    provider_charge_id: str
    status: str


@dataclass(frozen=True)
class Refund:
    id: int
    payment_id: int
    amount_cents: int
    provider_refund_id: str | None
    status: str
