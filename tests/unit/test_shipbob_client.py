"""Reading a case, a shipment and an order from ShipBob — and what happens when it goes wrong.

Every request here is answered by a stand-in ShipBob running in the same process, so
nothing reaches the network and the whole file runs in about a second.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from tests.fixtures.shipbob import (
    CASE_1001,
    NOT_FOUND_BODY,
    ORDER_1001,
    SHIPMENT_1001,
    case_payload,
    without,
)

from claim_agent.errors import NotFoundError, UpstreamError
from claim_agent.settings import Settings
from claim_agent.shipbob.client import ShipBobClient


@pytest.fixture
async def http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client aimed at the stand-in ShipBob, built the way the application builds one.

    The client under test never makes its own, so this is what a caller has to supply.
    """
    async with httpx.AsyncClient(
        base_url=settings.shipbob_base_url,
        timeout=settings.shipbob_timeout_seconds,
    ) as client:
        yield client


def build_client(http: httpx.AsyncClient, *, max_attempts: int = 1) -> ShipBobClient:
    """Build the client under test, with retrying switched off unless a test asks for it.

    A test that is not about retrying should not sit through the waits between
    attempts, so one attempt is the default here even though the application uses three.
    """
    return ShipBobClient(http, max_attempts=max_attempts)


async def test_reading_a_case_gives_back_the_merchants_claim(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.1: the case is where an investigation starts, and it names what to read next."""
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)

    case = await build_client(http).get_case("CASE-1001")

    assert case.case_id == "CASE-1001"
    assert case.shipment_id == "342578703"
    assert case.order_id == "334291211"
    assert case.account_name == "Best Paw Nutrition"


async def test_reading_a_shipment_says_whether_it_was_insured(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.1, FR-0.2: the shipment record is the only place insurance is stated."""
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)

    shipment = await build_client(http).get_shipment("342578703")

    assert shipment.shipment_id == "342578703"
    assert shipment.is_insured is False
    assert shipment.carrier == "Royal Mail Tracked 48"


async def test_reading_an_order_gives_back_the_products_and_their_prices(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.1, FR-0.5: what an order was worth is added up from the products on it."""
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)

    order = await build_client(http).get_order("334291211")

    assert order.order_id == "334291211"
    assert len(order.line_items) == 2
    assert order.line_items[0].sku == "AMP1"


async def test_money_arrives_with_its_cents_intact(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.6, FR-1.21: $38.00 has to stay $38.00, so no figure rests on an approximation."""
    # Written out by hand rather than built from a dictionary: turning a dictionary into
    # JSON in Python writes 38.00 as `38.0`, which is the very thing this test is here to
    # notice. This is what ShipBob actually sends.
    raw_order = (
        '{"order_id": "334291211", "user_id": "334430", "line_items": ['
        '{"product_id": "1374243085", "name": "Additional Collagen Ampoule Duo",'
        ' "sku": "AMP1", "quantity": 1, "unit_price": 38.00},'
        '{"product_id": "1309112104", "name": "Liposomal Tripeptide Collagen",'
        ' "sku": "COLLAGEN1", "quantity": 1, "unit_price": 52.00}],'
        '"created_date": "2026-02-07T07:42:48.000+0000"}'
    )
    shipbob.get("/orders/334291211").respond(200, text=raw_order, content_type="application/json")

    order = await build_client(http).get_order("334291211")

    unit_price = order.line_items[0].unit_price
    assert isinstance(unit_price, Decimal)
    # Two decimal places, still. `Decimal("38.0")` — what reading the reply the ordinary
    # way produces — would pass an equality check against 38.00 and fail this one.
    assert str(unit_price) == "38.00"
    assert unit_price.as_tuple().exponent == -2
    assert order.total_value == Decimal("90.00")


async def test_shipbobs_way_of_writing_a_time_is_understood(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.1: ShipBob ends its times with `+0000`, which names the same instant as `Z`."""
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/cases/CASE-9101").respond(
        200,
        json=case_payload(
            case_id="CASE-9101",
            delivered_date="2026-02-11T11:36:14Z",
            created_date="2026-02-19T14:20:16Z",
        ),
    )
    client = build_client(http)

    shipbob_style = await client.get_case("CASE-1001")
    zulu_style = await client.get_case("CASE-9101")

    assert shipbob_style.delivered_date == datetime(2026, 2, 11, 11, 36, 14, tzinfo=UTC)
    assert shipbob_style.delivered_date == zulu_style.delivered_date
    assert shipbob_style.created_date == zulu_style.created_date


async def test_an_unreachable_shipbob_is_tried_again_and_then_reported(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a claim is not lost to one slow moment, but nor does a read go on forever."""
    route = shipbob.get("/cases/CASE-1001").mock(side_effect=httpx.TimeoutException("too slow"))

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).get_case("CASE-1001")

    assert route.call_count == 3


async def test_one_attempt_means_exactly_one_request(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: the attempt count includes the first try, so one means no retrying at all."""
    route = shipbob.get("/cases/CASE-1001").mock(side_effect=httpx.TimeoutException("too slow"))

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=1).get_case("CASE-1001")

    assert route.call_count == 1


async def test_a_momentary_failure_at_shipbob_is_survived(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: ShipBob reporting a fault of its own is worth trying again."""
    route = shipbob.get("/cases/CASE-1001").mock(
        side_effect=[
            httpx.Response(500, json={"error": "internal"}),
            httpx.Response(200, json=CASE_1001),
        ]
    )

    case = await build_client(http, max_attempts=2).get_case("CASE-1001")

    assert case.case_id == "CASE-1001"
    assert route.call_count == 2


async def test_a_case_that_does_not_exist_is_reported_without_trying_again(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.1: "there is no such case" is a real answer, so asking twice would only waste time."""
    route = shipbob.get("/cases/CASE-9999").respond(404, json=NOT_FOUND_BODY)

    with pytest.raises(NotFoundError):
        await build_client(http, max_attempts=3).get_case("CASE-9999")

    assert route.call_count == 1


async def test_a_refused_request_is_reported_without_trying_again(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a request ShipBob will not accept will not be accepted the second time either."""
    route = shipbob.get("/cases/CASE-1001").respond(400, json={"error": "invalid_request"})

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).get_case("CASE-1001")

    assert route.call_count == 1


async def test_a_reply_that_is_not_json_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-4, NFR-6: a page of HTML from a proxy is a failure, not a case."""
    route = shipbob.get("/cases/CASE-1001").respond(
        200, text="<html>Service unavailable</html>", content_type="text/html"
    )

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).get_case("CASE-1001")

    assert route.call_count == 1


async def test_a_shipment_that_says_nothing_about_insurance_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-0.2: an insured claim follows another process, so silence must never read as "not insured"."""
    shipbob.get("/shipments/342578703").respond(200, json=without(SHIPMENT_1001, "is_insured"))

    with pytest.raises(UpstreamError):
        await build_client(http).get_shipment("342578703")


async def test_a_failure_tells_the_caller_nothing_internal(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: the reason a record was rejected goes to the logs; the caller gets a plain sentence."""
    shipbob.get("/shipments/342578703").respond(200, json=without(SHIPMENT_1001, "is_insured"))

    with pytest.raises(UpstreamError) as raised:
        await build_client(http).get_shipment("342578703")

    failure = raised.value
    assert failure.details == {"resource": "shipment", "resource_id": "342578703"}
    assert failure.message == "ShipBob returned a shipment that could not be read."
    for internal_detail in ("is_insured", "validation error", "pydantic", "Traceback", "http"):
        assert internal_detail not in failure.message


async def test_a_failure_never_repeats_the_address_it_was_reading(
    shipbob: respx.Router, settings: Settings
) -> None:
    """NFR-6: the ShipBob address may carry a password, so no message or detail may quote it."""
    shipbob.get("/cases/CASE-1001").mock(side_effect=httpx.ConnectError("refused"))
    address_with_password = settings.shipbob_base_url.replace("http://", "http://reader:hunter2@")

    async with httpx.AsyncClient(base_url=address_with_password, timeout=1.0) as http:
        with pytest.raises(UpstreamError) as raised:
            await build_client(http).get_case("CASE-1001")

    assert "hunter2" not in raised.value.message
    assert "hunter2" not in str(raised.value.details)


async def test_closing_the_client_closes_its_connections(settings: Settings) -> None:
    """NFR-6: a caller holding only this client can still shut it down tidily."""
    http = httpx.AsyncClient(base_url=settings.shipbob_base_url)

    await ShipBobClient(http).aclose()

    assert http.is_closed


def test_the_client_can_only_read_the_three_records() -> None:
    """FR-0.1, NFR-8: attachments, invoices, email and reimbursement are out of reach from here.

    Photographs are the expensive part of investigating a claim, and a claim turned away
    at the pre-flight screen must never pay for them. Keeping them unreachable is a
    property of the code, not a promise in a comment.
    """
    reachable = {name for name in dir(ShipBobClient) if not name.startswith("_")}

    assert reachable == {"get_case", "get_shipment", "get_order", "aclose"}
