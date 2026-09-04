"""Fetching the evidence an investigation runs on: a case's images, and a priced invoice.

A damaged-in-transit claim is argued from two things ShipBob hands over on request. The
first is the case's **attachments** — the photographs and screenshots the merchant
uploaded, which are the only record of what the damage looked like (FR-1.4). The second
is an **invoice**: ShipBob's priced list of what the shipment contained, generated when
asked for rather than stored, and the only figures a recommended reimbursement may be
worked out from (FR-1.18).

**Why this is not part of the client that reads a case, a shipment and an order.** That
client promises three reads and nothing else, because looking at photographs is the
expensive part of investigating a claim, and a claim turned away by the cheap pre-flight
screen must never pay for it (NFR-8). Putting these two calls beside those three would
make that promise untrue, and would let the cheap screen become expensive by accident. So
they live apart: only an investigation that has decided a claim is worth looking into
holds one of these.

**Reading only.** There is deliberately no way from here to email a merchant or submit a
reimbursement. Those two are irreversible, they happen only after a rep has approved them,
and they live somewhere an investigation cannot reach at all (FR-1.2).

Every way these calls can go wrong is a handled outcome with a plain message rather than a
crash (NFR-6), and the failures are told apart on purpose. "ShipBob will not price this
shipment" is a settled answer, which sends the claim to a human with a reason to give
them. "ShipBob could not be reached" is a fault that may well pass. A caller that could
not tell those two apart would report one as the other.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from claim_agent.domain.models import Attachment, Invoice
from claim_agent.errors import InvoiceUnavailableError, NotFoundError, UpstreamError
from claim_agent.observability import get_logger

logger = get_logger(__name__)

# The kind of record being read — an attachment listing or an invoice. Naming it lets the
# one shared reading function hand back the right type instead of something the caller has
# to check for itself.
Record = TypeVar("Record", bound=BaseModel)


class _AttachmentsReply(BaseModel):
    """The listing ShipBob returns for a case: its images, wrapped in an object.

    This exists only because the endpoint wraps the list rather than returning it bare.
    The images inside it are the ordinary `Attachment` records the rest of the system
    uses, unchanged.

    The list itself is **required**, with no default. A case with no attachments is
    answered with an empty list, and that is normal and meaningful — it means there is no
    evidence to look at, so the claim can only end in a request for information (FR-1.6).
    A reply that does not mention attachments at all is something else entirely: a reply
    we could not read. Defaulting it to empty would turn a failed read into "this merchant
    sent no photographs", which is the one confusion this must not allow (NFR-4).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    attachments: tuple[Attachment, ...]


class EvidenceClient:
    """Fetches a case's images and generates a shipment's invoice (FR-1.2).

    Give it a ready-made HTTP client with the ShipBob address and the timeout already set
    on it. It does not build its own, so the application decides how long connections
    live and can share one pool, and a test can hand in a client that answers from memory
    instead of over a network.

    `max_attempts` counts the first try, so the default of three means at most two
    retries. Only failures that could plausibly succeed next time are retried: a slow or
    unreachable ShipBob, or ShipBob reporting a fault of its own. A case that is not
    there, a shipment ShipBob will not price, a request it refuses, and a reply we cannot
    read are all settled answers, and asking again would only waste time (NFR-6).

    Every method either returns what was asked for or raises: `NotFoundError` when the
    case does not exist, `InvoiceUnavailableError` when ShipBob will not price a shipment,
    and `UpstreamError` for every other failure. Nothing here returns a half-filled
    record, or an empty list standing in for a problem, because an investigation must
    never mistake a failed read for absent evidence (FR-1.6, NFR-4).
    """

    def __init__(self, http: httpx.AsyncClient, *, max_attempts: int = 3) -> None:
        """Wrap an HTTP client that already knows the ShipBob address and timeout."""
        self._http = http
        self._max_attempts = max_attempts

    async def list_attachments(self, case_id: str) -> tuple[Attachment, ...]:
        """List the images a merchant uploaded to a case, by its case id.

        These are the photographs and screenshots an investigation reads: pictures of the
        damaged product, pictures of the box, a photograph of an invoice, a screenshot of
        the end customer reporting the damage. What each one actually shows can only be
        settled by looking at it — the file name and the file type say nothing about the
        content, so they are carried and never used to decide anything (FR-1.4).

        Returns them in the order ShipBob listed them. **An empty result means the case
        genuinely has no attachments**, which is an ordinary answer and not a failure: it
        means there is no evidence, so the claim can only end in a request for information
        (FR-1.6).

        Raises:
            NotFoundError: ShipBob has no case with this id.
            UpstreamError: ShipBob could not be reached, failed, or replied with something
                that is not a list of attachments.
        """
        # The case id is one segment of the address, so anything unusual in it — a slash,
        # a question mark — is escaped rather than allowed to change what gets read.
        path = f"/cases/{quote(case_id, safe='')}/attachments"
        context = {"case_id": case_id}
        response = await self._request("GET", path, resource="attachment list", context=context)

        if response.status_code == httpx.codes.NOT_FOUND:
            # "There is no such case" is a real answer, not a failure, so it is never
            # retried. The message names the case rather than its attachments, because a
            # case that does not exist is what a rep would need to hear about.
            raise NotFoundError(
                "ShipBob has no case with this id.",
                details={"resource": "attachment list", **context},
            )

        self._refuse_unless_successful(response, resource="attachment list", context=context)

        reply = _parse(response, _AttachmentsReply, resource="attachment list", context=context)
        return reply.attachments

    async def generate_invoice(self, *, shipment_id: str, user_id: str) -> Invoice:
        """Ask ShipBob to price what a shipment contained, and hand back the invoice.

        The invoice is what a recommended reimbursement is worked out from: the agent says
        which products were damaged, and the amount comes from these lines and nothing
        else (FR-1.18). Prices keep every cent exactly as ShipBob wrote them.

        Both ids are required because ShipBob asks for both. `user_id` identifies the
        merchant and is carried on the case; a caller that does not have one cannot make
        this call, and deciding what an unidentified merchant means for a claim is not
        this client's job.

        Raises:
            InvoiceUnavailableError: ShipBob will not price this shipment. A settled
                answer, so the claim needs a human rather than another attempt.
            UpstreamError: ShipBob could not be reached, failed, refused the request for
                any other reason, or replied with something that is not an invoice.
        """
        context = {"shipment_id": shipment_id}
        response = await self._request(
            "POST",
            "/invoices/generate",
            body={"shipment_id": shipment_id, "user_id": user_id},
            resource="invoice",
            context=context,
        )

        if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            # Any refusal of this shape is treated as "ShipBob will not price this
            # shipment", whatever short code comes with it, because a refusal aimed at
            # this one request will be refused again next time. The code ShipBob gave goes
            # to the logs, where an engineer can see which refusal it was.
            logger.warning(
                "shipbob_invoice_unavailable",
                shipment_id=shipment_id,
                user_id=user_id,
                status_code=response.status_code,
                reported_code=_reported_code(response),
            )
            raise InvoiceUnavailableError(
                "ShipBob will not price this shipment.",
                details={"resource": "invoice", **context},
            )

        # There is deliberately no "not found" case here. This address does not name a
        # record, so a refusal from it says something is wrong with the request or with
        # ShipBob, not that a shipment is missing — and reporting a missing shipment would
        # send a rep looking for the wrong problem.
        self._refuse_unless_successful(response, resource="invoice", context=context)

        invoice = _parse(response, Invoice, resource="invoice", context=context)

        # An invoice is the only thing a payout may be priced from, so it has to be an
        # invoice for the shipment we asked about. REQUIREMENTS.md is explicit that a
        # well-formed reply from this API is not evidence of correctness — the
        # reimbursement endpoint approves every request put to it, including claims the
        # system decided to deny — so a reply is checked against what was asked for
        # rather than trusted for having arrived. Without this, a mismatched invoice
        # would quietly price a claim from another shipment's products.
        if invoice.shipment_id is not None and invoice.shipment_id != shipment_id:
            logger.warning(
                "shipbob_invoice_for_another_shipment",
                shipment_id=shipment_id,
                invoiced_shipment_id=invoice.shipment_id,
                invoice_id=invoice.invoice_id,
            )
            raise UpstreamError(
                "ShipBob returned an invoice for a different shipment.",
                details={"resource": "invoice", **context},
            )

        return invoice

    async def aclose(self) -> None:
        """Close the underlying connections.

        The application owns the HTTP client it handed in and may close it itself instead;
        this is here so a caller that has only this client can still shut it down tidily.
        Closing a client that is shared with another caller closes it for both of them.
        """
        await self._http.aclose()

    def _refuse_unless_successful(
        self, response: httpx.Response, *, resource: str, context: dict[str, str]
    ) -> None:
        """Turn any refusal we have not already made sense of into a handled failure.

        By the time this runs, ShipBob's own faults have been retried and given up on, and
        the answers that mean something to a caller — no such case, will not price this
        shipment — have been dealt with by the method that knows about them. Whatever is
        left is a refusal nobody expected, and it is reported rather than read.
        """
        if response.is_success:
            return

        logger.warning(
            "shipbob_read_refused",
            resource=resource,
            status_code=response.status_code,
            **context,
        )
        raise UpstreamError(
            f"ShipBob would not return the {resource}.",
            details={"resource": resource, **context},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, str] | None = None,
        resource: str,
        context: dict[str, str],
    ) -> httpx.Response:
        """Make a call to ShipBob, trying again when the failure might be temporary.

        Waits a fifth of a second before the first retry and twice that before the next,
        so a moment of trouble at ShipBob's end is not turned into a failed claim, and a
        real outage is not hammered. The wait is exactly the same every run: adding
        randomness would change no recommendation and would make the same claim take a
        different length of time twice.

        Comes back with whatever ShipBob said, including a refusal such as "no such case"
        or "I will not price this", which the caller makes sense of. Raises `UpstreamError`
        only once the attempts are used up.

        `resource` is the everyday name for what was being fetched ("invoice"), used in
        messages and logs. `context` is the identifier the call was about, and it is
        written into both the logs and any failure a caller sees.
        """
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception_type(UpstreamError),
            reraise=True,
        )
        # Annotated because the retry helper cannot know what the function it runs
        # returns; without this, everything downstream would lose its type.
        response: httpx.Response = await retrying(
            self._attempt, method, path, body=body, resource=resource, context=context
        )
        return response

    async def _attempt(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, str] | None,
        resource: str,
        context: dict[str, str],
    ) -> httpx.Response:
        """Make one call, failing only in the ways that are worth trying again.

        Being unable to reach ShipBob, and ShipBob reporting a fault of its own, are both
        worth another go. Everything else is handed back for the caller to judge.
        """
        try:
            response = await self._http.request(method, path, json=body)
        except httpx.TransportError as exc:
            # Covers a timeout as well: httpx counts a request that ran out of time as one
            # kind of transport failure, alongside a refused or dropped connection.
            logger.warning(
                "shipbob_unreachable",
                resource=resource,
                failure=type(exc).__name__,
                **context,
            )
            raise UpstreamError(
                f"ShipBob could not be reached to fetch the {resource}.",
                details={"resource": resource, **context},
            ) from exc

        if response.is_server_error:
            logger.warning(
                "shipbob_server_error",
                resource=resource,
                status_code=response.status_code,
                **context,
            )
            raise UpstreamError(
                f"ShipBob failed while fetching the {resource}.",
                details={"resource": resource, **context},
            )

        return response


def _parse(
    response: httpx.Response,
    model: type[Record],
    *,
    resource: str,
    context: dict[str, str],
) -> Record:
    """Turn a reply from ShipBob into a record, or refuse it.

    A reply that is not readable is refused rather than patched up: a claim decided on
    evidence we had to guess at would be worse than a claim that failed loudly (NFR-4).
    Neither problem improves on a second attempt, so neither is retried.

    The reason a reply was rejected — which field was missing or the wrong type — goes to
    the logs, where an engineer can act on it. The caller gets a plain sentence, because
    internal detail must not travel out through the API.

    Raises:
        UpstreamError: the reply was not JSON, or was not a record of this kind.
    """
    try:
        # Money arrives as a plain JSON number, such as 38.00. Reading the reply the usual
        # way would turn that into a binary floating point number first, and "38.00" would
        # come back as 38.0 — the same amount, but no longer a record of cents, and
        # amounts like 0.10 cannot be held exactly that way at all. Reading every number
        # straight into an exact decimal keeps the figure as ShipBob wrote it, so no
        # reimbursement is ever built on an approximation (FR-1.18, NFR-2). This looks
        # like a detour worth simplifying away. It is not: the ordinary readers both lose
        # the cents, quietly.
        payload = json.loads(response.text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        logger.warning("shipbob_reply_not_json", resource=resource, reason=str(exc), **context)
        raise UpstreamError(
            f"The {resource} ShipBob returned could not be read.",
            details={"resource": resource, **context},
        ) from exc

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "shipbob_reply_unusable",
            resource=resource,
            problems=exc.errors(include_url=False, include_input=False),
            **context,
        )
        raise UpstreamError(
            f"The {resource} ShipBob returned could not be read.",
            details={"resource": resource, **context},
        ) from exc


def _reported_code(response: httpx.Response) -> str | None:
    """Pull ShipBob's own short name for a refusal out of the reply, for the logs.

    ShipBob writes a refusal as an object with an `error` field holding a short code, such
    as `invoice_unavailable`. Knowing which refusal it was is what tells an engineer
    whether a shipment cannot be priced or the request was wrong, so it is worth reading —
    but nothing is decided from it, and a refusal that arrives in any other shape simply
    has no code to report.
    """
    try:
        body = json.loads(response.text)
    except json.JSONDecodeError:
        return None

    if not isinstance(body, dict):
        return None

    reported = body.get("error")
    return reported if isinstance(reported, str) else None
