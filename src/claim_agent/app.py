"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from claim_agent import __version__
from claim_agent.api.exception_handlers import register_exception_handlers
from claim_agent.api.middleware import RequestContextMiddleware
from claim_agent.api.routes import health, preflight
from claim_agent.observability import configure_logging, get_logger
from claim_agent.policy import Policy, get_policy
from claim_agent.settings import Settings, get_settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.storage.merchant_memory import MerchantMemory

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down hooks (clients, connection pools)."""
    logger.info("service_starting", version=__version__, environment=app.state.settings.environment)
    yield
    # The connections the ShipBob reader holds open are given back here, when a real
    # server stops. Only the closing happens here; see `create_app` for why the client
    # itself is not built here.
    await app.state.shipbob.aclose()
    logger.info("service_stopping")


def create_app(
    settings: Settings | None = None,
    policy: Policy | None = None,
    merchant_memory: MerchantMemory | None = None,
) -> FastAPI:
    """Build the application. Tests call this directly with overridden settings.

    Anything a route needs for the whole life of the process is built here and kept
    on the application, so a route reads it rather than making its own. Passing a
    merchant memory in is how a test starts with a merchant who already has
    corrections on file (FR-0.5).
    """
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
    # Built here and not in the start-up hook on purpose. A test drives the app in
    # this same process without ever starting a server, and that path runs no
    # start-up hook, so a reader built there would simply not exist by the time a
    # route asked for it. Building it here is safe because an HTTP client does not
    # attach itself to a running loop until its first request.
    app.state.shipbob = ShipBobClient(
        httpx.AsyncClient(
            base_url=settings.shipbob_base_url,
            timeout=settings.shipbob_timeout_seconds,
        ),
        max_attempts=settings.shipbob_max_attempts,
    )
    app.state.merchant_memory = merchant_memory or MerchantMemory(settings.database_path)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(preflight.router)
    return app


app = create_app()
