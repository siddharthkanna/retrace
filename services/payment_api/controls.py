"""Behaviour that can be switched while the service is running."""

from pydantic import BaseModel


class FeatureFlags(BaseModel):
    forward_idempotency_key: bool = True
    refund_row_locking: bool = True
