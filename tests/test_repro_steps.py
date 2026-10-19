import os
from uuid import uuid4

import pytest

from investigator.repro.recipe import Step
from investigator.repro.steps import InvalidRecipeError, run_steps

API = os.environ["PAYMENT_API_URL"]


def _post(path: str, **body) -> Step:
    request = {
        "method": "POST",
        "path": path,
        "headers": {"Idempotency-Key": str(uuid4())},
        "body": body,
    }
    return Step.model_validate({"requests": [request]})


def test_a_later_step_can_use_a_field_from_an_earlier_reply():
    charge = _post("/charge", order_id=f"order-{uuid4().hex[:8]}", amount_cents=3000)
    refund = _post("/refund", payment_id="$1.id", amount_cents=3000)

    (payment,), (refunded,) = run_steps([charge, refund], API)

    assert refunded["status"] == 200
    assert refunded["body"]["payment_id"] == payment["body"]["id"]


def test_a_reference_to_a_step_that_has_not_run_is_an_invalid_recipe():
    refund = _post("/refund", payment_id="$3.id", amount_cents=3000)

    with pytest.raises(InvalidRecipeError):
        run_steps([refund], API)


def test_a_missing_field_is_reported_with_what_the_system_replied():
    charge = Step.model_validate(
        {"requests": [{"method": "POST", "path": "/charge", "body": {"order_id": "x"}}]}
    )
    refund = _post("/refund", payment_id="$1.id", amount_cents=3000)

    with pytest.raises(InvalidRecipeError, match="(?i)status 422.*idempotency-key"):
        run_steps([charge, refund], API)


def test_a_malformed_reference_is_an_invalid_recipe():
    refund = _post("/refund", payment_id="$1.payment.id", amount_cents=3000)

    with pytest.raises(InvalidRecipeError, match="not a valid reference"):
        run_steps([refund], API)
