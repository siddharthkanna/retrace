"""Business logic for payments."""

import logging

from services.payment_api.errors import IdempotencyKeyReuseError
from services.payment_api.provider_client import ProviderClient
from services.payment_api.repository import PaymentRepository
from services.payment_api.schemas import (
    ChargeRequest,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
)

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, provider: ProviderClient, payments: PaymentRepository) -> None:
        self._provider = provider
        self._payments = payments

    def charge(self, req: ChargeRequest, idempotency_key: str) -> PaymentResponse:
        logger.info(
            "charge requested",
            extra={
                "order_id": req.order_id,
                "amount_cents": req.amount_cents,
                "idempotency_key": idempotency_key,
            },
        )
        existing = self._payments.find_payment_by_idempotency_key(idempotency_key)
        if existing is not None:
            if (existing.order_id, existing.amount_cents) != (req.order_id, req.amount_cents):
                raise IdempotencyKeyReuseError(idempotency_key)
            logger.info(
                "charge already processed, returning existing payment",
                extra={"payment_id": existing.id},
            )
            return PaymentResponse.model_validate(existing)

        provider_charge_id = self._provider.create_charge(
            req.order_id, req.amount_cents, idempotency_key
        )
        logger.info("provider charge created", extra={"provider_charge_id": provider_charge_id})
        payment = self._payments.insert_payment(
            req.order_id,
            req.amount_cents,
            provider_charge_id,
            status="succeeded",
            idempotency_key=idempotency_key,
        )
        logger.info("payment recorded", extra={"payment_id": payment.id, "order_id": req.order_id})
        return PaymentResponse.model_validate(payment)

    def refund(self, req: RefundRequest, idempotency_key: str) -> RefundResponse:
        logger.info(
            "refund requested",
            extra={
                "payment_id": req.payment_id,
                "amount_cents": req.amount_cents,
                "idempotency_key": idempotency_key,
            },
        )
        refund = self._payments.reserve_refund(req.payment_id, req.amount_cents, idempotency_key)
        if (refund.payment_id, refund.amount_cents) != (req.payment_id, req.amount_cents):
            raise IdempotencyKeyReuseError(idempotency_key)
        if refund.status == "succeeded":
            logger.info(
                "refund already processed, returning existing refund",
                extra={"refund_id": refund.id},
            )
            return RefundResponse.model_validate(refund)
        logger.info("refund reserved", extra={"refund_id": refund.id})

        # If the provider call fails, the refund stays 'pending'. A retry with the
        # same key resumes from here, and the provider ignores the repeated key.
        payment = self._payments.get_payment(refund.payment_id)
        provider_refund_id = self._provider.create_refund(
            payment.provider_charge_id, refund.amount_cents, idempotency_key
        )
        logger.info("provider refund created", extra={"provider_refund_id": provider_refund_id})
        refund = self._payments.complete_refund(refund.id, provider_refund_id)
        logger.info("refund completed", extra={"refund_id": refund.id})
        return RefundResponse.model_validate(refund)

    def check_dependencies(self) -> None:
        self._payments.ping()
        self._provider.ping()
