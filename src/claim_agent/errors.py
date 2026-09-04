"""Errors this service raises deliberately.

Each carries the HTTP status and machine-readable code its API response should
use, so handlers stay a single translation step rather than a decision tree.
"""

from __future__ import annotations

from typing import Any


class ClaimAgentError(Exception):
    """Base class for expected failures. Never used to signal a bug."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(ClaimAgentError):
    """A requested case, claim line, or report does not exist."""

    status_code = 404
    code = "not_found"


class InvalidRequestError(ClaimAgentError):
    """The caller asked for something the service will not do."""

    status_code = 400
    code = "invalid_request"


class ConflictError(ClaimAgentError):
    """The action contradicts current state — e.g. re-executing an executed line."""

    status_code = 409
    code = "conflict"


class UpstreamError(ClaimAgentError):
    """A dependency (ShipBob API, model provider) failed or was unreachable."""

    status_code = 502
    code = "upstream_unavailable"
