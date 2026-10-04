"""Endpoints that change feature flags and chaos settings at runtime."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.payment_api.controls import Chaos, FeatureFlags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _update(current: BaseModel, new: BaseModel) -> None:
    for name, value in new:
        setattr(current, name, value)


@router.get("/flags", response_model=FeatureFlags)
def get_flags(request: Request) -> FeatureFlags:
    return request.app.state.flags


@router.put("/flags", response_model=FeatureFlags)
def set_flags(new: FeatureFlags, request: Request) -> FeatureFlags:
    flags: FeatureFlags = request.app.state.flags
    logger.info(
        "feature flags updated",
        extra={"previous": flags.model_dump(), "current": new.model_dump()},
    )
    _update(flags, new)
    return flags


@router.put("/chaos", response_model=Chaos)
def set_chaos(new: Chaos, request: Request) -> Chaos:
    # Deliberately not logged: chaos stands in for failures nobody announced.
    chaos: Chaos = request.app.state.chaos
    _update(chaos, new)
    return chaos
