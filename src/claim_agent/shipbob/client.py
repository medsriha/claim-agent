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


Record = TypeVar("Record", bound=BaseModel)


class ShipBobClient:
    """Reads the three records a damaged-in-transit claim is built from (FR-0.1)."""

    def __init__(self, http: httpx.AsyncClient, *, max_attempts: int = 3) -> None:
        """Wrap an HTTP client that already knows the ShipBob address and timeout."""
        self._http = http
        self._max_attempts = max_attempts

    async def get_case(self, case_id: str) -> Case:
        """Fetch the support case a merchant opened, by its case id (for example CASE-1001)."""
        return await self._read(Case, resource="case", resource_id=case_id, collection="cases")

    async def get_shipment(self, shipment_id: str) -> Shipment:
        """Fetch the parcel record, by its shipment id."""
        return await self._read(
            Shipment, resource="shipment", resource_id=shipment_id, collection="shipments"
        )

    async def get_order(self, order_id: str) -> Order:
        """Fetch the order the goods came from, by its order id."""
        return await self._read(Order, resource="order", resource_id=order_id, collection="orders")

    async def aclose(self) -> None:
        """Close the underlying connections."""
        await self._http.aclose()

    async def _read(
        self,
        model: type[Record],
        *,
        resource: str,
        resource_id: str,
        collection: str,
    ) -> Record:
        """Read one record and turn it into the shape the rest of the system works with."""

        path = f"/{collection}/{quote(resource_id, safe='')}"
        response = await self._fetch(path, resource=resource, resource_id=resource_id)

        if response.status_code == httpx.codes.NOT_FOUND:
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
        """Ask ShipBob for a record, trying again when the failure might be temporary."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            retry=retry_if_exception_type(UpstreamError),
            reraise=True,
        )

        response: httpx.Response = await retrying(
            self._attempt, path, resource=resource, resource_id=resource_id
        )
        return response

    async def _attempt(self, path: str, *, resource: str, resource_id: str) -> httpx.Response:
        """Make one request, failing only in the ways that are worth trying again."""
        try:
            response = await self._http.get(path)
        except httpx.TransportError as exc:
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
    """Turn a reply from ShipBob into a record, or refuse it."""
    try:
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
