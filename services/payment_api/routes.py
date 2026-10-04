"""HTTP endpoints. No business logic here."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from services.payment_api.schemas import (
    ChargeRequest,
    HealthResponse,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
)
from services.payment_api.service import PaymentService

router = APIRouter()


def get_payment_service(request: Request) -> PaymentService:
    return request.app.state.payment_service


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=255)]


@router.get("/health", response_model=HealthResponse)
def health(payments: PaymentServiceDep) -> HealthResponse:
    payments.check_dependencies()
    return HealthResponse(status="ok")


@router.post("/charge", response_model=PaymentResponse)
def charge(
    req: ChargeRequest, idempotency_key: IdempotencyKey, payments: PaymentServiceDep
) -> PaymentResponse:
    return payments.charge(req, idempotency_key)


@router.post("/refund", response_model=RefundResponse)
def refund(
    req: RefundRequest, idempotency_key: IdempotencyKey, payments: PaymentServiceDep
) -> RefundResponse:
    return payments.refund(req, idempotency_key)
