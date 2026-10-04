"""Request and response models."""

from pydantic import BaseModel, ConfigDict, Field


class ChargeRequest(BaseModel):
    order_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)


class PaymentResponse(BaseModel):
    # Lets the response be built directly from a Payment row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: str
    amount_cents: int
    provider_charge_id: str
    status: str


class HealthResponse(BaseModel):
    status: str


class RefundRequest(BaseModel):
    payment_id: int
    amount_cents: int = Field(gt=0)


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    amount_cents: int
    provider_refund_id: str
    status: str
