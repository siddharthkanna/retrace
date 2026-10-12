"""Scenario 1: a customer is charged twice for one order."""

from scenarios.base import (
    GroundTruth,
    IncidentReport,
    Scenario,
    charge,
    new_order_id,
    set_flags,
    set_provider_chaos,
)


def trigger() -> IncidentReport:
    set_flags(forward_idempotency_key=False)
    set_provider_chaos(delay_next_charge_response_s=3)
    order_id = new_order_id()
    charge(order_id, 4999)
    return IncidentReport(
        description=f"A customer says they were charged twice (49.99 each) for order {order_id}.",
        severity="high",
        order_id=order_id,
    )


SCENARIO = Scenario(
    id="double_charge",
    trigger=trigger,
    ground_truth=GroundTruth(
        root_cause="retry_without_idempotency_key",
        explanation=(
            "The provider processed the charge but responded after the client timeout."
            " The payment API retried without forwarding the idempotency key, so the"
            " provider treated the retry as a new charge."
        ),
        key_evidence=(
            "feature flag forward_idempotency_key was set to false",
            "payment-api log: provider request timed out, retrying",
            "two provider 'charge created' logs in one trace, both with no idempotency key",
        ),
    ),
)
