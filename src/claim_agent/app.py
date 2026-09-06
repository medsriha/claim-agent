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
    # The connections the ShipBob reader holds open are given back here, when a real
    # server stops. Only the closing happens here; see `create_app` for why the client
    # itself is not built here.
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
    """Build the application. Tests call this directly with overridden settings.

    Anything a route needs for the whole life of the process is built here and kept
    on the application, so a route reads it rather than making its own. Passing a
    merchant memory in is how a test starts with a merchant who already has
    corrections on file (FR-0.5).
    Passing a report store in is how one starts with reports already decided on
    (FR-2.9b).

    The policy passed in is the one the service starts with. It is not kept as it
    is: the admin panel can change the thresholds while the service runs, so what
    routes actually read is a holder that can be given a new policy, and that
    remembers this one to go back to (FR-0.7).
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
    app.state.live_policy = LivePolicy(policy)
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
    # The images an investigation looks at live at a storage address that has nothing
    # to do with ShipBob's API, so they are fetched with a client of their own. Sharing
    # ShipBob's would mean sending its credentials to a storage host, which is the kind
    # of thing that only has to happen once to be a problem.
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
    # The conversations of every investigation, kept for the life of the process so a
    # send-back continues the investigation that wrote the report (FR-R.2).
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
