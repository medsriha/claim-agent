"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from claim_agent import __version__
from claim_agent.api.exception_handlers import register_exception_handlers
from claim_agent.api.middleware import RequestContextMiddleware
from claim_agent.api.routes import health
from claim_agent.observability import configure_logging, get_logger
from claim_agent.policy import Policy, get_policy
from claim_agent.settings import Settings, get_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down hooks (clients, connection pools)."""
    logger.info("service_starting", version=__version__, environment=app.state.settings.environment)
    yield
    logger.info("service_stopping")


def create_app(settings: Settings | None = None, policy: Policy | None = None) -> FastAPI:
    """Build the application. Tests call this directly with overridden settings."""
    settings = settings or get_settings()
    policy = policy or get_policy()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)

    app = FastAPI(
        title="Damaged-in-Transit Claims Agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.policy = policy
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
