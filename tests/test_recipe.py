import pytest
from pydantic import ValidationError

from investigator.repro.recipe import Recipe

REFUND = {"method": "POST", "path": "/refund", "body": {"payment_id": "$1.id"}}
VALID = {
    "settings": {"payment-api": {"refund_row_locking": False}},
    "steps": [
        {"requests": [{"method": "POST", "path": "/charge", "body": {"order_id": "repro-1"}}]},
        {"requests": [REFUND, REFUND]},
    ],
    "check_sql": "SELECT 1 FROM refunds",
}


def test_a_valid_recipe_is_accepted():
    recipe = Recipe.model_validate(VALID)

    assert len(recipe.steps[1].requests) == 2


def test_a_full_address_is_rejected_as_a_path():
    step = {"requests": [{"method": "GET", "path": "http://elsewhere.test/health"}]}

    with pytest.raises(ValidationError):
        Recipe.model_validate({**VALID, "steps": [step]})


def test_a_recipe_with_no_steps_is_rejected():
    with pytest.raises(ValidationError):
        Recipe.model_validate({**VALID, "steps": []})
