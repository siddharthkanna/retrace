"""Scenario 3: one payment is refunded twice."""

from concurrent.futures import ThreadPoolExecutor

from scenarios.base import (
    GroundTruth,
    IncidentReport,
    Scenario,
    charge,
    new_order_id,
    refund,
    restore_database,
    set_flags,
    slow_refund_writes,
)


def trigger() -> IncidentReport:
    order_id = new_order_id()
    payment = charge(order_id, 3000).json()
    set_flags(refund_row_locking=False)
    slow_refund_writes(0.3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: refund(payment["id"], 3000), range(2)))
    restore_database()
    return IncidentReport(
        description=f"Finance found 60.00 refunded against a 30.00 payment for order {order_id}.",
        severity="high",
        order_id=order_id,
    )


SCENARIO = Scenario(
    id="double_refund",
    trigger=trigger,
    ground_truth=GroundTruth(
        root_cause="refund_race_without_row_lock",
        explanation=(
            "With row locking off, two concurrent refunds each read the refunded total"
            " before the other had inserted, so both passed the balance check."
        ),
        key_evidence=(
            "feature flag refund_row_locking was set to false",
            "two overlapping POST /refund spans for the same payment",
            "two refund rows whose total exceeds the payment amount",
        ),
    ),
)
