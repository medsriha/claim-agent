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


class ModelAnswerDidNotFitError(UpstreamError):
    """The model answered, and the answer did not fit the form it was asked to fill in."""

    code = "model_answer_unusable"

    def __init__(
        self,
        message: str,
        *,
        problems: tuple[str, ...] = (),
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.problems = problems


class ConfigurationError(ClaimAgentError):
    """Something this service needs in order to work was never configured."""

    status_code = 503
    code = "configuration_error"


class ModelOutputRejectedError(ClaimAgentError):
    """The model answered in a way it is not allowed to, so its answer was thrown away."""

    status_code = 502
    code = "model_output_rejected"


class InvoiceUnavailableError(ClaimAgentError):
    """ShipBob will not price this shipment, and asking again will not change that."""

    status_code = 502
    code = "invoice_unavailable"


class StorageError(ClaimAgentError):
    """Our own store could not be read or written."""

    status_code = 503
    code = "storage_unavailable"
