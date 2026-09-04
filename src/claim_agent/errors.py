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


class ConfigurationError(ClaimAgentError):
    """Something this service needs in order to work was never configured.

    Kept apart from `UpstreamError` for the same reason `StorageError` is: the two
    send whoever is reading the message looking in different places. "The model
    provider could not be reached" starts an investigation into somebody else's
    system; "no API key was set" is answered by looking at our own configuration.
    Reporting the second as the first would waste the first hour of working out
    what went wrong.

    Raised when the thing is asked for, never while this module is being imported.
    The service has to start without credentials — that is how it is demonstrated
    with no model access at all — so a missing key stops the one request that
    needed it rather than the whole process (NFR-6).
    """

    status_code = 503
    code = "configuration_error"


class ModelOutputRejectedError(ClaimAgentError):
    """The model answered in a way it is not allowed to, so its answer was thrown away.

    Not a fault of the provider's and not a fault of the caller's: the model was
    reached, it replied, and the reply broke a rule the system does not bend. The
    case this exists for is money — the model writes the wording of a merchant
    email and may never write a figure in it, because no monetary amount may come
    from model output (FR-1.21). An email describing itself as a draft is the other
    case, since a rep has to read the exact words that would be sent (FR-1.17).

    Deliberately **not** a kind of `UpstreamError`, for a reason worth stating
    plainly: the model wrapper tries again on any of those. A reply that broke a
    rule would then be silently re-asked rather than stopping the run, and the
    second answer might break the rule differently. It also sends a reader
    somewhere useless — nothing is unreachable, and no amount of waiting mends it.

    The claim goes to a person, carrying what was established (NFR-4).
    """

    status_code = 502
    code = "model_output_rejected"


class InvoiceUnavailableError(ClaimAgentError):
    """ShipBob will not price this shipment, and asking again will not change that.

    A settled answer rather than a fault, which is why it is deliberately **not** a
    kind of `UpstreamError`: the retry rule in the ShipBob clients asks again on any
    `UpstreamError`, and this is the one upstream reply where asking again only
    wastes a claim's time.

    It matters that a caller can tell this apart from ShipBob being unreachable. A
    shipment ShipBob will not price cannot have a reimbursement worked out for it,
    so the claim goes to a person with that reason to give them; a shipment we
    could not ask about is a fault that may well pass (FR-1.18, NFR-4).

    The status is the one a caller would get if this ever travelled out of the API,
    which it should not: an investigation turns it into an escalation long before
    then. `502` rather than ShipBob's own `422`, because `422` is what FastAPI
    itself returns for a malformed request and the two would be confused.
    """

    status_code = 502
    code = "invoice_unavailable"


class StorageError(ClaimAgentError):
    """Our own store could not be read or written.

    Kept apart from `UpstreamError` because the two send a reader looking in
    different places: one means an outside system is having trouble, this one
    means ours is. Reporting a full disk as "ShipBob is unavailable" would waste
    the first hour of working out what went wrong.
    """

    status_code = 503
    code = "storage_unavailable"
