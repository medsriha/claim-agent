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


Record = TypeVar("Record", bound=BaseModel)


class _AttachmentsReply(BaseModel):
    """The listing ShipBob returns for a case: its images, wrapped in an object."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    attachments: tuple[Attachment, ...]


class EvidenceClient:
    """Fetches a case's images and generates a shipment's invoice (FR-1.2)."""

    def __init__(self, http: httpx.AsyncClient, *, max_attempts: int = 3) -> None:
        """Wrap an HTTP client that already knows the ShipBob address and timeout."""
        self._http = http
        self._max_attempts = max_attempts

    async def list_attachments(self, case_id: str) -> tuple[Attachment, ...]:
        """List the images a merchant uploaded to a case, by its case id."""

        path = f"/cases/{quote(case_id, safe='')}/attachments"
        context = {"case_id": case_id}
        response = await self._request("GET", path, resource="attachment list", context=context)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(
                "ShipBob has no case with this id.",
                details={"resource": "attachment list", **context},
            )

        self._refuse_unless_successful(response, resource="attachment list", context=context)

        reply = _parse(response, _AttachmentsReply, resource="attachment list", context=context)
        return reply.attachments

    async def generate_invoice(self, *, shipment_id: str, user_id: str) -> Invoice:
        """Ask ShipBob to price what a shipment contained, and hand back the invoice."""
        context = {"shipment_id": shipment_id}
        response = await self._request(
            "POST",
            "/invoices/generate",
            body={"shipment_id": shipment_id, "user_id": user_id},
            resource="invoice",
            context=context,
        )

        if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            if _looks_like_a_complaint_about_our_request(response):
                logger.warning(
                    "shipbob_refused_our_invoice_request",
                    shipment_id=shipment_id,
                    status_code=response.status_code,
                )
                raise UpstreamError(
                    "ShipBob would not accept the request for an invoice.",
                    details={"resource": "invoice", **context},
                )

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

        self._refuse_unless_successful(response, resource="invoice", context=context)

        invoice = _parse(response, Invoice, resource="invoice", context=context)

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
        """Close the underlying connections."""
        await self._http.aclose()

    def _refuse_unless_successful(
        self, response: httpx.Response, *, resource: str, context: dict[str, str]
    ) -> None:
        """Turn any refusal we have not already made sense of into a handled failure."""
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
        """Make a call to ShipBob, trying again when the failure might be temporary."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception_type(UpstreamError),
            reraise=True,
        )

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
        """Make one call, failing only in the ways that are worth trying again."""
        try:
            response = await self._http.request(method, path, json=body)
        except httpx.TransportError as exc:
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
    """Turn a reply from ShipBob into a record, or refuse it."""
    try:
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


def _looks_like_a_complaint_about_our_request(response: httpx.Response) -> bool:
    """Say whether a refusal is about the request we sent rather than about the shipment."""
    try:
        body = json.loads(response.text)
    except json.JSONDecodeError:
        return False

    if not isinstance(body, dict):
        return False

    return "detail" in body and "error" not in body


def _reported_code(response: httpx.Response) -> str | None:
    """Pull ShipBob's own short name for a refusal out of the reply, for the logs."""
    try:
        body = json.loads(response.text)
    except json.JSONDecodeError:
        return None

    if not isinstance(body, dict):
        return None

    reported = body.get("error")
    return reported if isinstance(reported, str) else None
