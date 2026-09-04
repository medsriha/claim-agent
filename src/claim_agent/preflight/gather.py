"""Reading the three records a claim is screened from (FR-0.1).

A claim arrives as a support case a merchant opened. The case names a parcel and an
order, and those three records together are everything the pre-flight screen needs in
order to decide whether the claim can be looked into at all. Nothing else is read here,
and in particular no attachments: attachments are photographs, looking at photographs is
the expensive part of investigating a claim, and a claim turned away at the screen has to
cost three cheap reads and nothing more (NFR-8).

The one thing in this file worth reading slowly is the difference between a record that
is not there and a record we could not read. The two look similar and mean opposite
things, and keeping them apart is the whole reason this file exists rather than the
screen calling the reader directly. `_read_if_named` explains it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from claim_agent.errors import NotFoundError
from claim_agent.preflight.models import CaseRecord
from claim_agent.shipbob.client import ShipBobClient

# The kind of record being fetched — a parcel or an order. Naming it lets one helper
# serve both reads and still hand each caller back the right type.
Record = TypeVar("Record", bound=BaseModel)


async def gather_case_record(case_id: str, client: ShipBobClient) -> CaseRecord:
    """Read the case, its parcel and its order, and hand the three back together (FR-0.1).

    The case is read first because it is the record that names the other two. Those
    two are then read at the same time as each other: neither needs anything from the
    other, so waiting for one to finish before starting the other would only make a
    merchant wait longer for the same answer.

    Args:
        case_id: The support case to screen, for example `CASE-1001`.
        client: The reader for the ShipBob API.

    Returns:
        The three records in one place. The parcel and the order are `None` when the
        case named neither, and when ShipBob has no record with the id the case gave.
        That is not a failure: it is the missing-information signal one of the four
        eligibility checks looks for, and the claim goes on to be screened and to
        produce a proper explanation for the merchant (FR-0.2, FR-0.4).

    Raises:
        NotFoundError: ShipBob has no case with this id. There is nothing to screen.
        UpstreamError: ShipBob could not be reached, failed, or replied with something
            we could not read — for the case, the parcel or the order alike.
    """
    case = await client.get_case(case_id)
    shipment, order = await asyncio.gather(
        _read_if_named(client.get_shipment, case.shipment_id),
        _read_if_named(client.get_order, case.order_id),
    )
    return CaseRecord(case=case, shipment=shipment, order=order)


async def _read_if_named(
    read: Callable[[str], Awaitable[Record]], record_id: str | None
) -> Record | None:
    """Read one of the records the case points at, if it points at one at all.

    Args:
        read: The function that fetches this kind of record by its id.
        record_id: The id the case gave, or `None` if the case gave none.

    Returns:
        The record; or `None` when the case named no id, and when ShipBob has no
        record with the id it did name. Both mean the same thing to the screen —
        information this claim needs is not there — and the claim is still screened
        so the merchant can be told exactly what was missing (FR-0.2).

    Raises:
        UpstreamError: ShipBob could not be reached, failed, or replied with something
            we could not read. Deliberately not turned into a missing record; see the
            comment below before changing it.
    """
    if record_id is None:
        return None
    try:
        return await read(record_id)
    except NotFoundError:
        # This catches one failure and nothing else, on purpose. "ShipBob has no such
        # record" is a fact about the claim; "ShipBob is having a bad morning" is a
        # fact about today, and the two must never be made to look alike. Widening
        # this to catch an upstream failure too would let a passing outage close a
        # perfectly good claim and send the merchant an email saying their claim was
        # missing information — an email nobody can take back, caused by nothing more
        # than a timeout. So an upstream failure is left to travel up and stop the
        # screen with an error a person sees instead (NFR-4, NFR-6).
        return None
