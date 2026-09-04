"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from claim_agent import __version__
from claim_agent.api.deps import SettingsDep

router = APIRouter(tags=["health"])


class Health(BaseModel):
    """Service liveness."""

    status: str
    version: str
    environment: str


@router.get("/health", summary="Liveness check")
async def health(settings: SettingsDep) -> Health:
    """Report that the process is up."""
    return Health(status="ok", version=__version__, environment=settings.environment)
