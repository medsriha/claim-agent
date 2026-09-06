from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from claim_agent import __version__
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.threads import PassThreads
from claim_agent.api.exception_handlers import register_exception_handlers
from claim_agent.api.middleware import RequestContextMiddleware
from claim_agent.api.routes import (
    admin,
    analysis,
    health,
    investigate,
    precedent,
    preflight,
    reports,
)
from claim_agent.live_policy import LivePolicy
from claim_agent.observability import configure_logging, get_logger
from claim_agent.policy import Policy, get_policy
from claim_agent.settings import Settings, get_settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down hooks (clients, connection pools)."""
    logger.info("service_starting", version=__version__, environment=app.state.settings.environment)
    yield

    await app.state.shipbob.aclose()
    await app.state.evidence.aclose()
    await app.state.attachment_http.aclose()
    logger.info("service_stopping")


def create_app(
    settings: Settings | None = None,
    policy: Policy | None = None,
    merchant_memory: MerchantMemory | None = None,
    precedent_store: PrecedentStore | None = None,
    report_store: ReportStore | None = None,
) -> FastAPI:
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
    app.state.live_policy = LivePolicy(policy)

    app.state.shipbob = ShipBobClient(
        httpx.AsyncClient(
            base_url=settings.shipbob_base_url,
            timeout=settings.shipbob_timeout_seconds,
        ),
        max_attempts=settings.shipbob_max_attempts,
    )

    app.state.evidence = EvidenceClient(
        httpx.AsyncClient(
            base_url=settings.shipbob_base_url,
            timeout=settings.shipbob_timeout_seconds,
        ),
        max_attempts=settings.shipbob_max_attempts,
    )
    app.state.attachment_http = httpx.AsyncClient(
        timeout=settings.attachment_timeout_seconds, follow_redirects=False
    )
    app.state.image_fetcher = ImageFetcher(app.state.attachment_http, settings)
    app.state.merchant_memory = merchant_memory or MerchantMemory(settings.database_path)
    app.state.precedent_store = precedent_store or PrecedentStore(settings.database_path)
    app.state.report_store = report_store or ReportStore(settings.database_path)
    app.state.decision_store = DecisionStore(settings.database_path)

    app.state.pass_threads = PassThreads()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(preflight.router)
    app.include_router(investigate.router)
    app.include_router(admin.router)
    app.include_router(precedent.router)
    app.include_router(analysis.router)
    app.include_router(reports.router)
    return app


app = create_app()
