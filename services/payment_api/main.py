"""Payment API: charges customers through the payment provider and records the result."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool

from services.common.telemetry import setup_telemetry
from services.payment_api.admin import router as admin_router
from services.payment_api.config import get_settings
from services.payment_api.controls import FeatureFlags
from services.payment_api.errors import (
    IdempotencyKeyReuseError,
    PaymentNotFoundError,
    RefundExceedsPaymentError,
)
from services.payment_api.provider_client import ProviderClient, ProviderError
from services.payment_api.repository import PaymentRepository
from services.payment_api.routes import router
from services.payment_api.service import PaymentService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    flags = FeatureFlags()
    pool = ConnectionPool(settings.database_url, open=True)
    provider = ProviderClient(
        settings.provider_url, settings.provider_timeout_s, settings.provider_max_retries, flags
    )
    app.state.flags = flags
    app.state.payment_service = PaymentService(provider, PaymentRepository(pool, flags))
    yield
    provider.close()
    pool.close()


app = FastAPI(title="payment-api", lifespan=lifespan)
setup_telemetry(app, "payment-api", get_settings().telemetry_database_url)
app.include_router(router)
app.include_router(admin_router)


def _rejected(request: Request, status_code: int, reason: str) -> JSONResponse:
    """Log why a request was refused, then tell the caller."""
    logger.warning(
        "request rejected",
        extra={"path": request.url.path, "status_code": status_code, "reason": reason},
    )
    return JSONResponse(status_code=status_code, content={"detail": reason})


@app.exception_handler(ProviderError)
def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "payment provider error"})


@app.exception_handler(IdempotencyKeyReuseError)
def idempotency_key_reuse_handler(request: Request, exc: IdempotencyKeyReuseError) -> JSONResponse:
    return _rejected(request, 422, "idempotency key was already used with a different request")


@app.exception_handler(PaymentNotFoundError)
def payment_not_found_handler(request: Request, exc: PaymentNotFoundError) -> JSONResponse:
    return _rejected(request, 404, "payment not found")


@app.exception_handler(RefundExceedsPaymentError)
def refund_exceeds_payment_handler(
    request: Request, exc: RefundExceedsPaymentError
) -> JSONResponse:
    return _rejected(request, 409, "refund exceeds amount paid")


@app.exception_handler(Exception)
def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled error",
        exc_info=exc,
        extra={"path": request.url.path, "error": f"{type(exc).__name__}: {exc}"},
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
