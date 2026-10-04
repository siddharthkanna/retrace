"""Runtime switches used to make the system misbehave on purpose."""

from pydantic import BaseModel


class FeatureFlags(BaseModel):
    """Behaviour settings. Turning one off is a realistic regression."""

    forward_idempotency_key: bool = True
    refund_row_locking: bool = True


class Chaos(BaseModel):
    """Simulated environmental failures. Hidden from the investigator."""

    fail_next_payment_insert: bool = False
    refund_check_delay_ms: int = 0
