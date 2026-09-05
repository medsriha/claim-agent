"""A stand-in for the ShipBob API, so the system has something to read on a laptop.

Screening a claim reads three records over the network: the support case, the parcel and
the order (FR-0.1). Investigating one reads two more: the images the merchant uploaded to
the case, and an invoice pricing what the parcel contained (FR-1.4, FR-1.18). Tests
intercept all five reads inside the process, which is why the test suite has never needed
a server. A person clicking through the screen is not a test — the reads are real — so
without something answering them, every claim fails as "ShipBob could not be reached".

This is that something. It answers the same five addresses the real ShipBob does, from the
same sample records the tests use, so the screen and the tests can never disagree about
what CASE-1001 looks like.

**It is a development tool.** It holds nine claims, has no security of any kind, and
implements none of ShipBob's API beyond the five reads this system makes. Nothing in
`src/` can reach it, and production never runs it.

The two endpoints that would send an email to a merchant or move money are deliberately
absent. Nothing in this system may reach them without a person approving first (FR-1.2),
and a stand-in that answered them would be a way to find that out the hard way.

Run it with `make mock`, which serves it on port 8080 — the address
`SHIPBOB_BASE_URL` already points at by default.
"""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from tests.fixtures.attachments import (
    ATTACHMENTS_1001,
    ATTACHMENTS_1002,
    ATTACHMENTS_1003,
    ATTACHMENTS_1004,
    ATTACHMENTS_1005,
    INVOICE_UNAVAILABLE_BODY,
    attachments_payload,
    invoice_from_order,
)
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    CASE_NOT_FOUND_BODY,
    CONSTRUCTED_HIGH_VALUE_CASE,
    CONSTRUCTED_HIGH_VALUE_ORDER,
    CONSTRUCTED_HIGH_VALUE_SHIPMENT,
    CONSTRUCTED_INSURED_CASE,
    CONSTRUCTED_INSURED_ORDER,
    CONSTRUCTED_INSURED_SHIPMENT,
    CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
    CONSTRUCTED_INSURED_SUBCATEGORY_ORDER,
    CONSTRUCTED_INSURED_SUBCATEGORY_SHIPMENT,
    CONSTRUCTED_LOST_IN_TRANSIT_CASE,
    CONSTRUCTED_LOST_IN_TRANSIT_ORDER,
    CONSTRUCTED_LOST_IN_TRANSIT_SHIPMENT,
    CONSTRUCTED_REPEAT_MERCHANT_CASE,
    CONSTRUCTED_REPEAT_MERCHANT_ORDER,
    CONSTRUCTED_REPEAT_MERCHANT_SHIPMENT,
    ORDER_1001,
    ORDER_1002,
    ORDER_1003,
    ORDER_1004,
    ORDER_1005,
    ORDER_NOT_FOUND_BODY,
    SHIPMENT_1001,
    SHIPMENT_1002,
    SHIPMENT_1003,
    SHIPMENT_1004,
    SHIPMENT_1005,
    SHIPMENT_NOT_FOUND_BODY,
)

CASES = [
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    CONSTRUCTED_INSURED_CASE,
    CONSTRUCTED_LOST_IN_TRANSIT_CASE,
    CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
    CONSTRUCTED_HIGH_VALUE_CASE,
    CONSTRUCTED_REPEAT_MERCHANT_CASE,
]

SHIPMENTS = [
    SHIPMENT_1001,
    SHIPMENT_1002,
    SHIPMENT_1003,
    SHIPMENT_1004,
    SHIPMENT_1005,
    CONSTRUCTED_INSURED_SHIPMENT,
    CONSTRUCTED_LOST_IN_TRANSIT_SHIPMENT,
    CONSTRUCTED_INSURED_SUBCATEGORY_SHIPMENT,
    CONSTRUCTED_HIGH_VALUE_SHIPMENT,
    CONSTRUCTED_REPEAT_MERCHANT_SHIPMENT,
]

ORDERS = [
    ORDER_1001,
    ORDER_1002,
    ORDER_1003,
    ORDER_1004,
    ORDER_1005,
    CONSTRUCTED_INSURED_ORDER,
    CONSTRUCTED_LOST_IN_TRANSIT_ORDER,
    CONSTRUCTED_INSURED_SUBCATEGORY_ORDER,
    CONSTRUCTED_HIGH_VALUE_ORDER,
    CONSTRUCTED_REPEAT_MERCHANT_ORDER,
]


def _by_id(records: list[dict[str, object]], id_field: str) -> dict[str, dict[str, object]]:
    """Index records by the id they carry, so a lookup does not scan the whole list.

    Raises `ValueError` if two records share an id, which would otherwise mean one of
    them silently became unreachable.
    """
    indexed: dict[str, dict[str, object]] = {}
    for record in records:
        record_id = str(record[id_field])
        if record_id in indexed:
            raise ValueError(f"Two sample records share the id {record_id}.")
        indexed[record_id] = record
    return indexed


CASES_BY_ID = _by_id(CASES, "case_id")
SHIPMENTS_BY_ID = _by_id(SHIPMENTS, "shipment_id")
ORDERS_BY_ID = _by_id(ORDERS, "order_id")

# The images ShipBob holds against each of the five sample cases, exactly as it serves
# them: real ids, real names, and signed addresses that really do fetch the image.
ATTACHMENTS_BY_CASE_ID: dict[str, dict[str, object]] = {
    "CASE-1001": ATTACHMENTS_1001,
    "CASE-1002": ATTACHMENTS_1002,
    "CASE-1003": ATTACHMENTS_1003,
    "CASE-1004": ATTACHMENTS_1004,
    "CASE-1005": ATTACHMENTS_1005,
}

# What the five constructed cases answer with. ShipBob supplied no images for cases we
# made up, and inventing addresses for them would put fabricated evidence in front of an
# investigation — once an image is fetched, nothing distinguishes one we invented from a
# photograph a merchant really took. An empty listing is the honest answer, and it is an
# ordinary answer rather than a failure (FR-1.6). It costs four of them nothing: they exist
# to be turned away by pre-flight, which happens before any image is read.
#
# CASE-9005 is the exception and it is meant to be. It passes the gates and is investigated,
# so an empty listing is what the investigation actually works from and the only honest
# recommendation is to go back to the merchant. That is enough for what it demonstrates —
# a correction carried across from the merchant's earlier claim (FR-C.8) — and giving it
# invented photographs to reach a payment instead is the exact trade this comment refuses.
EMPTY_ATTACHMENT_LISTING = attachments_payload()


def _as_money(value: object) -> object:
    """Turn a price into an exact decimal, keeping its cents.

    The sample records write prices as ordinary Python numbers, where 38.00 and 38.0 are
    the same thing. ShipBob writes money with its cents, and the system is built to read
    it that way, so restoring the cents here is what makes the stand-in behave like the
    real API rather than like a rounded copy of it.
    """
    if isinstance(value, float | int):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    return value


def _with_money_restored(record: dict[str, object]) -> dict[str, object]:
    """Copy an order with every line's price turned back into an exact decimal."""
    line_items = record.get("line_items")
    if not isinstance(line_items, list):
        return record
    return {
        **record,
        "line_items": [
            {**item, "unit_price": _as_money(item.get("unit_price"))}
            if isinstance(item, dict)
            else item
            for item in line_items
        ],
    }


def _to_json(value: object) -> str:
    """Write a record as JSON, with money as a bare number that keeps its cents.

    This exists for one reason: Python's ordinary JSON writer cannot produce `38.00`.
    Given a float it writes `38.0`, and given an exact decimal it refuses outright. The
    real API sends money as a plain number *with* its cents, and the system is carefully
    written to read those cents (see the note in the ShipBob client), so a stand-in that
    dropped them would quietly stop exercising the thing that matters most about money.

    Everything that is not a decimal is handed to the ordinary writer, so nothing else
    about the shape of a record changes.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        pairs = (f"{json.dumps(str(key))}: {_to_json(item)}" for key, item in value.items())
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_to_json(item) for item in value) + "]"
    return json.dumps(value)


def _delay_seconds() -> float:
    """How long to hold every answer back, in seconds.

    Zero unless `SHIPBOB_MOCK_DELAY_SECONDS` says otherwise. Set it to see the screen's
    waiting state, or set it above the system's own timeout to see what a representative
    sees when ShipBob is too slow to answer (NFR-6). An unreadable value means zero:
    a development tool refusing to start over a typo helps nobody.
    """
    raw = os.environ.get("SHIPBOB_MOCK_DELAY_SECONDS", "0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


app = FastAPI(
    title="ShipBob mock API (development stand-in)",
    description="Serves the sample claim records so the claims agent has something to read.",
)


async def _hold_the_answer_back() -> None:
    """Wait as long as the delay setting asks before answering anything.

    Every address goes through this, so switching the delay on slows the whole stand-in
    rather than only the reads, and a slow ShipBob looks the same from the screen
    whichever record it was asked for (NFR-6).
    """
    delay = _delay_seconds()
    if delay:
        await asyncio.sleep(delay)


async def _answer(
    record: dict[str, object] | None,
    missing_body: dict[str, object] = CASE_NOT_FOUND_BODY,
) -> Response:
    """Send a record back the way ShipBob would, or say there is no such record.

    A missing record is answered as a proper 404 rather than an error, because a claim
    for a case that does not exist is a normal thing to demonstrate: the system turns
    that into "ShipBob has no case with this id" for the representative.

    The body naming the missing resource differs per read, the way ShipBob's does, so
    the stand-in cannot teach a caller that every 404 looks alike.
    """
    await _hold_the_answer_back()
    if record is None:
        return Response(
            content=_to_json(missing_body),
            status_code=404,
            media_type="application/json",
        )
    return Response(content=_to_json(record), media_type="application/json")


@app.get("/cases", summary="List every support case")
async def list_cases() -> Response:
    """Return a short entry for every claim, the way ShipBob's own listing does.

    **Only five fields per case, and that is the point.** ShipBob's listing does not carry
    the order, the shipment, the merchant or the account name, so nothing can work out
    which claims are related to one another from this alone — each one has to be read in
    full afterwards. Serving a fuller record here would be more convenient and would
    teach a caller something untrue about what the real API gives them.

    The order is the order the records are declared in, so two runs of the demo list the
    claims the same way (NFR-1).
    """
    listing = [
        {
            "case_id": case["case_id"],
            "case_number": case["case_number"],
            "status": case["status"],
            "subject": case["subject"],
            "created_date": case["created_date"],
        }
        for case in CASES
    ]
    await _hold_the_answer_back()
    return Response(content=_to_json({"cases": listing}), media_type="application/json")


@app.get("/cases/{case_id}", summary="Read one support case")
async def get_case(case_id: str) -> Response:
    """Return the merchant's claim, or 404 if there is no such case."""
    return await _answer(CASES_BY_ID.get(case_id))


@app.get("/shipments/{shipment_id}", summary="Read one shipment")
async def get_shipment(shipment_id: str) -> Response:
    """Return the parcel record, or 404 if there is no such shipment."""
    return await _answer(SHIPMENTS_BY_ID.get(shipment_id), SHIPMENT_NOT_FOUND_BODY)


@app.get("/orders/{order_id}", summary="Read one order")
async def get_order(order_id: str) -> Response:
    """Return the order and its line items, or 404 if there is no such order."""
    record = ORDERS_BY_ID.get(order_id)
    return await _answer(
        None if record is None else _with_money_restored(record), ORDER_NOT_FOUND_BODY
    )


@app.get("/cases/{case_id}/attachments", summary="List the images on one support case")
async def get_case_attachments(case_id: str) -> Response:
    """Return the images the merchant uploaded to a case (FR-1.4).

    A case that exists but carries no images answers with an empty list, not a 404. That
    distinction is the whole of CASE-1005: having sent nothing is a finding about the
    claim, which ends in a request for information, whereas a 404 means nobody knows
    (FR-1.6). A case id ShipBob has never heard of is the 404, answered exactly as the
    other reads answer one.
    """
    if case_id not in CASES_BY_ID:
        return await _answer(None)
    return await _answer(ATTACHMENTS_BY_CASE_ID.get(case_id, EMPTY_ATTACHMENT_LISTING))


class InvoiceRequest(BaseModel):
    """What ShipBob's invoice endpoint is asked for: which parcel, and whose account."""

    shipment_id: str
    user_id: str


@app.post("/invoices/generate", summary="Price what a shipment contained")
async def generate_invoice(invoice_request: InvoiceRequest) -> Response:
    """Return the invoice for a shipment, or refuse to price one we have no order for.

    The invoice is the only document a recommended reimbursement may be worked out from
    (FR-1.18), and its lines are identical to the order's, so it is built from the order
    the shipment came from rather than written out separately. The two can then never
    disagree about what the parcel held.

    A shipment this stand-in has never heard of is answered `422 invoice_unavailable`.
    That is ShipBob refusing to price a particular shipment, which is a settled answer
    rather than an outage, and handling it is required (FR-1.18). Every sample shipment
    can be priced, so without this there would be no way at all to see that path run —
    and a required behaviour nobody can demonstrate is one nobody has checked.
    """
    await _hold_the_answer_back()
    order = _order_for_shipment(invoice_request.shipment_id)
    if order is None:
        return Response(
            content=_to_json(INVOICE_UNAVAILABLE_BODY),
            status_code=422,
            media_type="application/json",
        )
    invoice = invoice_from_order(order, shipment_id=invoice_request.shipment_id)
    return Response(content=_to_json(_with_money_restored(invoice)), media_type="application/json")


def _order_for_shipment(shipment_id: str) -> dict[str, object] | None:
    """Find the order a shipment came from, or nothing if either is unknown.

    Nothing means the shipment cannot be priced, which is what the invoice endpoint
    refuses on.
    """
    shipment = SHIPMENTS_BY_ID.get(shipment_id)
    if shipment is None:
        return None
    return ORDERS_BY_ID.get(str(shipment["order_id"]))
