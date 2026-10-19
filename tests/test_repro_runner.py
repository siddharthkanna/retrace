import os
from uuid import uuid4

import httpx
import pytest

from investigator.repro.recipe import Recipe
from investigator.repro.runner import Target, run_recipe
from scenarios.base import slow_refund_writes

API = os.environ["PAYMENT_API_URL"]
FLAGS = f"{API}/admin/flags"


@pytest.fixture
def target(target_pool) -> Target:
    return Target(api_url=API, config_sources={"payment-api": FLAGS}, pool=target_pool)


def _post(path: str, **body) -> dict:
    return {
        "method": "POST",
        "path": path,
        "headers": {"Idempotency-Key": str(uuid4())},
        "body": body,
    }


def _double_refund(**fields) -> Recipe:
    """Charge an order, then refund it in full twice at the same moment."""
    order_id = f"order-{uuid4().hex[:8]}"
    recipe = {
        "steps": [
            {"requests": [_post("/charge", order_id=order_id, amount_cents=3000)]},
            {
                "requests": [
                    _post("/refund", payment_id="$1.id", amount_cents=3000),
                    _post("/refund", payment_id="$1.id", amount_cents=3000),
                ]
            },
        ],
        "check_sql": (
            "SELECT 1 FROM refunds r JOIN payments p ON p.id = r.payment_id"
            f" WHERE p.order_id = '{order_id}'"
            " GROUP BY p.id HAVING sum(r.amount_cents) > p.amount_cents"
        ),
    }
    return Recipe.model_validate({**recipe, **fields})


def test_a_recipe_that_causes_the_incident_is_reproduced_and_settings_are_put_back(target):
    slow_refund_writes(0.3)
    recipe = _double_refund(settings={"payment-api": {"refund_row_locking": False}})

    result = run_recipe(recipe, target)

    assert result.outcome == "reproduced"
    assert httpx.get(FLAGS).json()["refund_row_locking"] is True


def test_a_recipe_that_does_not_cause_the_incident_is_not_reproduced(target):
    slow_refund_writes(0.3)

    assert run_recipe(_double_refund(), target).outcome == "not_reproduced"


def test_a_check_that_is_already_true_is_an_invalid_recipe(target):
    result = run_recipe(_double_refund(check_sql="SELECT 1"), target)

    assert result.outcome == "invalid_recipe"
    assert "before the steps" in result.detail


def test_a_setting_the_system_does_not_have_is_an_invalid_recipe(target):
    recipe = _double_refund(settings={"payment-api": {"no_such_setting": False}})

    result = run_recipe(recipe, target)

    assert result.outcome == "invalid_recipe"
    assert "no_such_setting" in result.detail
