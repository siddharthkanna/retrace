"""Endpoints that read and change feature flags at runtime."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.payment_api.controls import FeatureFlags

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
    previous, current = flags.model_dump(), new.model_dump()
    if previous != current:
        logger.info("feature flags updated", extra={"previous": previous, "current": current})
    _update(flags, new)
    return flags
