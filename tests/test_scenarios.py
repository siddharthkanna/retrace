"""Each scenario must actually produce its incident."""

import os

import httpx
import psycopg

from scenarios import charge_without_record, double_charge, double_refund
from scenarios.base import PROVIDER, charge, new_order_id, set_provider_chaos


def _provider_charges(order_id: str) -> int:
    return sum(c["order_id"] == order_id for c in httpx.get(f"{PROVIDER}/charges").json())


def _scalar(sql: str, order_id: str) -> int:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return conn.execute(sql, (order_id,)).fetchone()[0]


def test_double_charge():
    incident = double_charge.trigger()
    assert _provider_charges(incident.order_id) == 2
    assert _scalar("SELECT count(*) FROM payments WHERE order_id = %s", incident.order_id) == 1


def test_retry_is_safe_when_the_key_is_forwarded():
    set_provider_chaos(delay_next_charge_response_s=3)
    order_id = new_order_id()
    assert charge(order_id, 4999).status_code == 200
    assert _provider_charges(order_id) == 1


def test_charge_without_record():
    incident = charge_without_record.trigger()
    assert _provider_charges(incident.order_id) == 1
    assert _scalar("SELECT count(*) FROM payments WHERE order_id = %s", incident.order_id) == 0


def test_double_refund():
    incident = double_refund.trigger()
    refunded = _scalar(
        "SELECT sum(r.amount_cents) FROM refunds r JOIN payments p ON p.id = r.payment_id"
        " WHERE p.order_id = %s",
        incident.order_id,
    )
    assert refunded == 6000
