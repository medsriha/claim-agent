"""Translate exceptions into a single, consistent error response shape."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger

logger = get_logger(__name__)


async def handle_claim_agent_error(_: Request, exc: Exception) -> JSONResponse:
    """Render a deliberate failure using the status and code it carries."""
    assert isinstance(exc, ClaimAgentError)  # noqa: S101 — registered for this type only
    logger.warning("request_failed", code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    """Log the cause, return nothing that reveals internals (security default)."""
    logger.exception("unhandled_error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {},
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the handlers above onto `app`."""
    app.add_exception_handler(ClaimAgentError, handle_claim_agent_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
