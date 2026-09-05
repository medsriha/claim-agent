from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from claim_agent import __version__
from claim_agent.api.deps import SettingsDep

router = APIRouter(tags=["health"])


class Health(BaseModel):
    """What the health check answers with."""

    status: str
    version: str
    environment: str


@router.get("/health", summary="Liveness check")
async def health(settings: SettingsDep) -> Health:
    """Answer that the service is running.

    Deliberately checks nothing external. If this reached out to ShipBob, a slow
    ShipBob would make a perfectly healthy service look dead and get it restarted.
    """
    return Health(status="ok", version=__version__, environment=settings.environment)
