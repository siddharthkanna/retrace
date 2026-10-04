"""Fake payment provider. Stands in for a real one such as Stripe."""

import logging
import os
import threading
import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from services.common.telemetry import setup_telemetry

logger = logging.getLogger(__name__)

app = FastAPI(title="provider-mock")
setup_telemetry(
    app, "provider-mock", os.environ["TELEMETRY_DATABASE_URL"], excluded_urls="admin/chaos"
)

# ponytail: charges and refunds live in memory and reset on restart; move to
# Postgres if provider events need to survive restarts.
charges: list[dict] = []
charges_by_key: dict[str, dict] = {}
refunds: list[dict] = []
refunds_by_key: dict[str, dict] = {}
# Makes "check the key, then create" a single step when requests arrive together.
_lock = threading.Lock()


class ChargeRequest(BaseModel):
    order_id: str
    amount_cents: int = Field(gt=0)


class RefundRequest(BaseModel):
    charge_id: str
    amount_cents: int = Field(gt=0)


class Chaos(BaseModel):
    """Simulated provider problems. Hidden from the investigator."""

    delay_next_charge_response_s: float = 0


chaos = Chaos()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.put("/admin/chaos", response_model=Chaos)
def set_chaos(new: Chaos) -> Chaos:
    chaos.delay_next_charge_response_s = new.delay_next_charge_response_s
    return chaos


@app.post("/charges")
def create_charge(req: ChargeRequest, idempotency_key: Annotated[str | None, Header()] = None):
    with _lock:
        charge = _create_or_replay_charge(req, idempotency_key)
        delay_s, chaos.delay_next_charge_response_s = chaos.delay_next_charge_response_s, 0
    # The charge already exists; only the response is late.
    time.sleep(delay_s)
    return charge


def _create_or_replay_charge(req: ChargeRequest, idempotency_key: str | None) -> dict:
    if idempotency_key is not None and idempotency_key in charges_by_key:
        charge = charges_by_key[idempotency_key]
        logger.info(
            "charge replayed for idempotency key",
            extra={"charge_id": charge["charge_id"], "idempotency_key": idempotency_key},
        )
        return charge
    charge = {
        "charge_id": f"ch_{uuid4().hex[:12]}",
        "order_id": req.order_id,
        "amount_cents": req.amount_cents,
        "created_at": datetime.now(UTC).isoformat(),
    }
    charges.append(charge)
    if idempotency_key is not None:
        charges_by_key[idempotency_key] = charge
    logger.info(
        "charge created",
        extra={**charge, "idempotency_key": idempotency_key},
    )
    return charge


@app.get("/charges")
def list_charges():
    return charges


@app.post("/refunds")
def create_refund(req: RefundRequest, idempotency_key: Annotated[str | None, Header()] = None):
    with _lock:
        if idempotency_key is not None and idempotency_key in refunds_by_key:
            refund = refunds_by_key[idempotency_key]
            logger.info(
                "refund replayed for idempotency key",
                extra={"refund_id": refund["refund_id"], "idempotency_key": idempotency_key},
            )
            return refund
        if not any(c["charge_id"] == req.charge_id for c in charges):
            raise HTTPException(status_code=404, detail="charge not found")
        refund = {
            "refund_id": f"re_{uuid4().hex[:12]}",
            "charge_id": req.charge_id,
            "amount_cents": req.amount_cents,
            "created_at": datetime.now(UTC).isoformat(),
        }
        refunds.append(refund)
        if idempotency_key is not None:
            refunds_by_key[idempotency_key] = refund
        logger.info(
            "refund created",
            extra={**refund, "idempotency_key": idempotency_key},
        )
        return refund


@app.get("/refunds")
def list_refunds():
    return refunds
