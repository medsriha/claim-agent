"""Reading a case, its shipment and its order from the ShipBob API.

A claim begins as a support case a merchant opened. That case names an order and a
shipment, and those three records together are everything the pre-flight screen needs
in order to decide whether the claim can be processed at all (FR-0.1).

**Three reads and nothing else.** There is deliberately no way from here to list a
case's attachments, generate an invoice, email a merchant, or pay a reimbursement.
Attachments are photographs, and looking at photographs is the expensive part of
investigating a claim, so they are only ever fetched once a claim has been found worth
investigating — a claim turned away at the pre-flight screen must cost a few cheap
reads and nothing more (FR-0.1, NFR-8). Emailing and paying happen only after a human
has approved them, and live somewhere this code cannot reach.

Reads fail in ordinary ways — ShipBob is slow, a network drops, a record is not there —
and every one of those is a handled outcome with a clear message rather than a crash
(NFR-6). A failure that might be temporary is tried again a few times before it is
given up on.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from claim_agent.domain.models import Case, Order, Shipment
from claim_agent.errors import NotFoundError, UpstreamError
from claim_agent.observability import get_logger

logger = get_logger(__name__)

# The kind of record being read — a case, a shipment or an order. Naming it lets the
# one shared read function hand back the right type instead of something the caller
# has to check for itself.
Record = TypeVar("Record", bound=BaseModel)


class ShipBobClient:
    """Reads the three records a damaged-in-transit claim is built from (FR-0.1).

    Give it a ready-made HTTP client with the ShipBob address and the timeout already
    set on it. It does not build its own, so the application decides how long
    connections live and can share one pool across every claim, and a test can hand in
    a client that answers from memory instead of over a network.

    `max_attempts` counts the first try, so the default of three means at most two
    retries. Only failures that could plausibly succeed next time are retried: a slow
    or unreachable ShipBob, or ShipBob reporting a fault of its own. A record that is
    not there, a request ShipBob refuses, and a reply we cannot read are all settled
    answers, and asking again would only waste time (NFR-6).

    Every method either returns the record or raises: `NotFoundError` when ShipBob has
    no such record, and `UpstreamError` for every other failure. Nothing here returns
    a half-filled record or a `None` standing in for a problem, because the pre-flight
    screen must never mistake a failed read for a missing field (FR-0.2, NFR-4).
    """

    def __init__(self, http: httpx.AsyncClient, *, max_attempts: int = 3) -> None:
        """Wrap an HTTP client that already knows the ShipBob address and timeout."""
        self._http = http
        self._max_attempts = max_attempts

    async def get_case(self, case_id: str) -> Case:
        """Fetch the support case a merchant opened, by its case id (for example CASE-1001).

        The case is the starting point of an investigation: it carries the merchant's own
        description of what happened and the ids of the order and shipment to read next.

        Raises:
            NotFoundError: ShipBob has no case with this id.
            UpstreamError: ShipBob could not be reached, failed, or replied with
                something that is not a case.
        """
        return await self._read(Case, resource="case", resource_id=case_id, collection="cases")

    async def get_shipment(self, shipment_id: str) -> Shipment:
        """Fetch the parcel record, by its shipment id.

        This is the only place that says whether the shipment was insured, and an
        insured claim follows a completely different process (FR-0.2).

        Raises:
            NotFoundError: ShipBob has no shipment with this id.
            UpstreamError: ShipBob could not be reached, failed, or replied with
                something that is not a shipment.
        """
        return await self._read(
            Shipment, resource="shipment", resource_id=shipment_id, collection="shipments"
        )

    async def get_order(self, order_id: str) -> Order:
        """Fetch the order the goods came from, by its order id.

        The order lists the products and their prices, which is what the value of a
        claim is worked out from (FR-0.5).

        Raises:
            NotFoundError: ShipBob has no order with this id.
            UpstreamError: ShipBob could not be reached, failed, or replied with
                something that is not an order.
        """
        return await self._read(Order, resource="order", resource_id=order_id, collection="orders")

    async def aclose(self) -> None:
        """Close the underlying connections.

        The application owns the HTTP client it handed in and may close it itself
        instead; this is here so a caller that has only the ShipBob client can still
        shut it down tidily.
        """
        await self._http.aclose()

    async def _read(
        self,
        model: type[Record],
        *,
        resource: str,
        resource_id: str,
        collection: str,
    ) -> Record:
        """Read one record and turn it into the shape the rest of the system works with.

        This is the whole of the reading logic; the three public methods differ only in
        which record they ask for. `resource` is the everyday word for it ("case"), used
        in messages and logs; `collection` is the matching part of the address ("cases").
        """
        # An id is one segment of the address, so anything unusual in it — a slash, a
        # question mark — is escaped rather than allowed to change which record is read.
        path = f"/{collection}/{quote(resource_id, safe='')}"
        response = await self._fetch(path, resource=resource, resource_id=resource_id)

        if response.status_code == httpx.codes.NOT_FOUND:
            # "There is no such record" is a real answer, not a failure, so it is never
            # retried. The caller decides what a missing record means for the claim.
            raise NotFoundError(
                f"ShipBob has no {resource} with this id.",
                details={"resource": resource, "resource_id": resource_id},
            )

        if not response.is_success:
            logger.warning(
                "shipbob_read_refused",
                resource=resource,
                resource_id=resource_id,
                status_code=response.status_code,
            )
            raise UpstreamError(
                f"ShipBob would not return the {resource}.",
                details={"resource": resource, "resource_id": resource_id},
            )

        return _parse(response, model, resource=resource, resource_id=resource_id)

    async def _fetch(self, path: str, *, resource: str, resource_id: str) -> httpx.Response:
        """Ask ShipBob for a record, trying again when the failure might be temporary.

        Waits a fifth of a second before the first retry and twice that before the next,
        so a moment of trouble at ShipBob's end is not turned into a failed claim, and a
        real outage is not hammered. The wait is exactly the same every run: adding
        randomness would change no verdict and would make the same claim take a
        different length of time twice (FR-0.6).

        Comes back with whatever ShipBob said, including a refusal such as "no such
        record", which the caller makes sense of. Raises `UpstreamError` only once the
        attempts are used up.
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
            self._attempt, path, resource=resource, resource_id=resource_id
        )
        return response

    async def _attempt(self, path: str, *, resource: str, resource_id: str) -> httpx.Response:
        """Make one request, failing only in the ways that are worth trying again.

        Being unable to reach ShipBob, and ShipBob reporting a fault of its own, are
        both worth another go. Everything else is handed back for the caller to judge.
        """
        try:
            response = await self._http.get(path)
        except httpx.TransportError as exc:
            # Covers a timeout as well: httpx counts a request that ran out of time as
            # one kind of transport failure, alongside a refused or dropped connection.
            logger.warning(
                "shipbob_unreachable",
                resource=resource,
                resource_id=resource_id,
                failure=type(exc).__name__,
            )
            raise UpstreamError(
                f"ShipBob could not be reached to read the {resource}.",
                details={"resource": resource, "resource_id": resource_id},
            ) from exc

        if response.is_server_error:
            logger.warning(
                "shipbob_server_error",
                resource=resource,
                resource_id=resource_id,
                status_code=response.status_code,
            )
            raise UpstreamError(
                f"ShipBob failed while returning the {resource}.",
                details={"resource": resource, "resource_id": resource_id},
            )

        return response


def _parse(
    response: httpx.Response,
    model: type[Record],
    *,
    resource: str,
    resource_id: str,
) -> Record:
    """Turn a reply from ShipBob into a record, or refuse it.

    A reply that is not readable is refused rather than patched up: a claim decided on
    a record we had to guess at would be worse than a claim that failed loudly (NFR-4).
    Neither problem improves on a second attempt, so neither is retried.

    The reason a record was rejected — which field was missing or the wrong type — goes
    to the logs, where an engineer can act on it. The caller gets a plain sentence,
    because internal detail must not travel out through the API.

    Raises:
        UpstreamError: the reply was not JSON, or was not a record of this kind.
    """
    try:
        # Money arrives as a plain JSON number, such as 38.00. Reading the reply the
        # usual way would turn that into a binary floating point number first, and
        # "38.00" would come back as 38.0 — the same amount, but no longer a record of
        # cents, and amounts like 0.10 cannot be held exactly that way at all. Reading
        # every number straight into an exact decimal keeps the figure as ShipBob wrote
        # it, so no reimbursement is ever built on an approximation (FR-0.6, FR-1.21).
        # This looks like a detour worth simplifying away. It is not: the ordinary
        # readers both lose the cents, quietly.
        payload = json.loads(response.text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        logger.warning(
            "shipbob_reply_not_json",
            resource=resource,
            resource_id=resource_id,
            reason=str(exc),
        )
        raise UpstreamError(
            f"ShipBob returned a {resource} that could not be read.",
            details={"resource": resource, "resource_id": resource_id},
        ) from exc

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "shipbob_reply_unusable",
            resource=resource,
            resource_id=resource_id,
            problems=exc.errors(include_url=False, include_input=False),
        )
        raise UpstreamError(
            f"ShipBob returned a {resource} that could not be read.",
            details={"resource": resource, "resource_id": resource_id},
        ) from exc
