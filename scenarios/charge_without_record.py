"""Scenario 2: the customer is charged but the payment is never recorded."""

from scenarios.base import (
    GroundTruth,
    Incident,
    Scenario,
    charge,
    new_order_id,
    set_payment_chaos,
)


def trigger() -> Incident:
    set_payment_chaos(fail_next_payment_insert=True)
    order_id = new_order_id()
    charge(order_id, 2500)
    return Incident(
        report=(
            f"A customer was charged 25.00 for order {order_id} but saw an error,"
            " and the order still shows as unpaid."
        ),
        order_id=order_id,
    )


SCENARIO = Scenario(
    id="charge_without_record",
    trigger=trigger,
    ground_truth=GroundTruth(
        root_cause="charge_not_recorded_after_database_failure",
        explanation=(
            "The provider charge succeeded, then the database insert failed. The payment"
            " API has no compensation step, so the charge was neither recorded nor reversed."
        ),
        key_evidence=(
            "provider log: charge created",
            "payment-api log: unhandled error with a database OperationalError",
            "no row in payments for the order",
        ),
    ),
)
