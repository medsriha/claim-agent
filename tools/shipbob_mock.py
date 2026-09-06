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
    """Index records by the id they carry, so a lookup does not scan the whole list."""
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


ATTACHMENTS_BY_CASE_ID: dict[str, dict[str, object]] = {
    "CASE-1001": ATTACHMENTS_1001,
    "CASE-1002": ATTACHMENTS_1002,
    "CASE-1003": ATTACHMENTS_1003,
    "CASE-1004": ATTACHMENTS_1004,
    "CASE-1005": ATTACHMENTS_1005,
}


EMPTY_ATTACHMENT_LISTING = attachments_payload()


def _as_money(value: object) -> object:
    """Turn a price into an exact decimal, keeping its cents."""
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
    """Write a record as JSON, with money as a bare number that keeps its cents."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        pairs = (f"{json.dumps(str(key))}: {_to_json(item)}" for key, item in value.items())
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_to_json(item) for item in value) + "]"
    return json.dumps(value)


def _delay_seconds() -> float:
    """How long to hold every answer back, in seconds."""
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
    """Wait as long as the delay setting asks before answering anything."""
    delay = _delay_seconds()
    if delay:
        await asyncio.sleep(delay)


async def _answer(
    record: dict[str, object] | None,
    missing_body: dict[str, object] = CASE_NOT_FOUND_BODY,
) -> Response:
    """Send a record back the way ShipBob would, or say there is no such record."""
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
    """Return a short entry for every claim, the way ShipBob's own listing does."""
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
    """Return the images the merchant uploaded to a case (FR-1.4)."""
    if case_id not in CASES_BY_ID:
        return await _answer(None)
    return await _answer(ATTACHMENTS_BY_CASE_ID.get(case_id, EMPTY_ATTACHMENT_LISTING))


class InvoiceRequest(BaseModel):
    """What ShipBob's invoice endpoint is asked for: which parcel, and whose account."""

    shipment_id: str
    user_id: str


@app.post("/invoices/generate", summary="Price what a shipment contained")
async def generate_invoice(invoice_request: InvoiceRequest) -> Response:
    """Return the invoice for a shipment, or refuse to price one we have no order for."""
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
    """Find the order a shipment came from, or nothing if either is unknown."""
    shipment = SHIPMENTS_BY_ID.get(shipment_id)
    if shipment is None:
        return None
    return ORDERS_BY_ID.get(str(shipment["order_id"]))
