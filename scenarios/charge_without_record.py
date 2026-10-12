"""Scenario 2: the customer is charged but the payment is never recorded."""

import threading
import time

from scenarios.base import (
    GroundTruth,
    IncidentReport,
    Scenario,
    charge,
    drop_database_connections,
    new_order_id,
    set_provider_chaos,
    wait_until_healthy,
)


def trigger() -> IncidentReport:
    order_id = new_order_id()
    # The provider takes a second to answer. Halfway through, the database drops the
    # payment API's connections, so the charge succeeds and recording it fails.
    set_provider_chaos(delay_next_charge_response_s=1)
    request = threading.Thread(target=charge, args=(order_id, 2500))
    request.start()
    time.sleep(0.5)
    drop_database_connections()
    request.join()
    wait_until_healthy()
    return IncidentReport(
        description=(
            f"A customer was charged 25.00 for order {order_id} but saw an error,"
            " and the order still shows as unpaid."
        ),
        severity="high",
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
            "payment-api log: discarding closed connection, then an unhandled OperationalError",
            "no row in payments for the order",
        ),
    ),
)
