"""Errors raised by the business logic."""


class IdempotencyKeyReuseError(Exception):
    """An idempotency key was reused with a different request."""


class PaymentNotFoundError(Exception):
    """No payment exists with the given ID."""


class RefundExceedsPaymentError(Exception):
    """The refund would bring the total refunded above the amount paid."""
