from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from claim_agent.errors import NotFoundError
from claim_agent.preflight.models import CaseRecord
from claim_agent.shipbob.client import ShipBobClient

Record = TypeVar("Record", bound=BaseModel)


async def gather_case_record(case_id: str, client: ShipBobClient) -> CaseRecord:
    """Read a case and its referenced shipment and order."""
    case = await client.get_case(case_id)
    shipment, order = await asyncio.gather(
        _read_if_named(client.get_shipment, case.shipment_id),
        _read_if_named(client.get_order, case.order_id),
    )
    return CaseRecord(case=case, shipment=shipment, order=order)


async def _read_if_named(
    read: Callable[[str], Awaitable[Record]], record_id: str | None
) -> Record | None:
    """Read a referenced record, treating a missing record as absent."""
    if record_id is None:
        return None
    try:
        return await read(record_id)
    except NotFoundError:
        return None
