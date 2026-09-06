from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from tests.fixtures.attachments import (
    ATTACHMENTS_1003,
    ATTACHMENTS_1005,
    INVOICE_342578703,
    INVOICE_UNAVAILABLE_BODY,
    attachment_payload,
    attachments_payload,
    invoice_payload,
)
from tests.fixtures.shipbob import CASE_NOT_FOUND_BODY, without

from claim_agent.errors import InvoiceUnavailableError, NotFoundError, UpstreamError
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient


@pytest.fixture
async def http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=settings.shipbob_base_url,
        timeout=settings.shipbob_timeout_seconds,
    ) as client:
        yield client


def build_client(http: httpx.AsyncClient, *, max_attempts: int = 1) -> EvidenceClient:
    return EvidenceClient(http, max_attempts=max_attempts)


async def test_listing_attachments_gives_back_the_images_on_the_case(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json=ATTACHMENTS_1003)

    attachments = await build_client(http).list_attachments("CASE-1003")

    assert [attachment.attachment_id for attachment in attachments] == [
        "ATT-CASE-1003-01",
        "ATT-CASE-1003-02",
        "ATT-CASE-1003-03",
    ]

    assert "/case-1003/01_Inv.png?" in attachments[0].url


async def test_a_file_name_and_type_are_carried_and_nothing_is_read_into_them(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json=ATTACHMENTS_1003)

    attachments = await build_client(http).list_attachments("CASE-1003")

    assert attachments[0].file_name == "Inv.png"
    assert {attachment.content_type for attachment in attachments} == {"image/png"}


async def test_a_case_with_no_attachments_is_an_ordinary_answer(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1005/attachments").respond(200, json=ATTACHMENTS_1005)

    attachments = await build_client(http).list_attachments("CASE-1005")

    assert attachments == ()


async def test_attachments_for_a_case_that_does_not_exist_are_reported_once(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.get("/cases/CASE-9999/attachments").respond(404, json=CASE_NOT_FOUND_BODY)

    with pytest.raises(NotFoundError):
        await build_client(http, max_attempts=3).list_attachments("CASE-9999")

    assert route.call_count == 1


async def test_an_unreachable_shipbob_is_tried_again_and_then_reported(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.get("/cases/CASE-1003/attachments").mock(
        side_effect=httpx.TimeoutException("too slow")
    )

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).list_attachments("CASE-1003")

    assert route.call_count == 3


async def test_a_momentary_failure_at_shipbob_is_survived(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.post("/invoices/generate").mock(
        side_effect=[
            httpx.Response(500, json={"error": "internal"}),
            httpx.Response(200, json=INVOICE_342578703),
        ]
    )

    invoice = await build_client(http, max_attempts=2).generate_invoice(
        shipment_id="342578703", user_id="334430"
    )

    assert invoice.invoice_id == "INV-342578703"
    assert route.call_count == 2
    assert json.loads(route.calls.last.request.content) == {
        "shipment_id": "342578703",
        "user_id": "334430",
    }


async def test_a_reply_that_is_not_json_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.get("/cases/CASE-1003/attachments").respond(
        200, text="<html>Service unavailable</html>", content_type="text/html"
    )

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).list_attachments("CASE-1003")

    assert route.call_count == 1


async def test_a_reply_that_never_mentions_attachments_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json={})

    with pytest.raises(UpstreamError):
        await build_client(http).list_attachments("CASE-1003")


async def test_an_attachment_with_no_address_to_fetch_it_from_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").respond(
        200, json=attachments_payload(without(attachment_payload(), "url"))
    )

    with pytest.raises(UpstreamError):
        await build_client(http).list_attachments("CASE-1003")


async def test_an_unusual_case_id_cannot_reach_a_different_address(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    requested: list[bytes] = []

    def record(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.raw_path)
        return httpx.Response(200, json=ATTACHMENTS_1005)

    shipbob.route(method="GET").mock(side_effect=record)

    await build_client(http).list_attachments("../orders/334291211")

    assert requested == [b"/cases/..%2Forders%2F334291211/attachments"]


async def test_generating_an_invoice_prices_what_the_shipment_contained(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)

    invoice = await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")

    assert invoice.invoice_id == "INV-342578703"
    assert invoice.shipment_id == "342578703"
    assert [line.sku for line in invoice.line_items] == ["AMP1", "COLLAGEN1"]
    assert invoice.generated_at == datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)
    assert json.loads(route.calls.last.request.content) == {
        "shipment_id": "342578703",
        "user_id": "334430",
    }


async def test_invoiced_money_arrives_with_its_cents_intact(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    raw_invoice = (
        '{"invoice_id": "INV-342578703", "shipment_id": "342578703", "line_items": ['
        '{"name": "Additional Collagen Ampoule Duo", "sku": "AMP1",'
        ' "quantity": 1, "unit_price": 38.00},'
        '{"name": "Liposomal Tripeptide Collagen", "sku": "COLLAGEN1",'
        ' "quantity": 1, "unit_price": 52.00}],'
        '"generated_at": "2026-03-21T10:00:00.000+0000"}'
    )
    shipbob.post("/invoices/generate").respond(
        200, text=raw_invoice, content_type="application/json"
    )

    invoice = await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")

    unit_price = invoice.line_items[0].unit_price
    assert unit_price == Decimal("38.00")

    assert isinstance(unit_price, Decimal)

    assert str(unit_price) == "38.00"
    assert unit_price.as_tuple().exponent == -2


async def test_shipbob_refusing_to_price_a_shipment_is_its_own_answer(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.post("/invoices/generate").respond(422, json=INVOICE_UNAVAILABLE_BODY)

    with pytest.raises(InvoiceUnavailableError) as raised:
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")

    failure = raised.value

    assert not isinstance(failure, UpstreamError)
    assert failure.code == "invoice_unavailable"

    assert failure.status_code == 502
    assert failure.details == {"resource": "invoice", "shipment_id": "342578703"}


async def test_a_shipment_shipbob_will_not_price_is_not_asked_about_again(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.post("/invoices/generate").respond(422, json=INVOICE_UNAVAILABLE_BODY)

    with pytest.raises(InvoiceUnavailableError):
        await build_client(http, max_attempts=3).generate_invoice(
            shipment_id="342578703", user_id="334430"
        )

    assert route.call_count == 1


@pytest.mark.parametrize(
    "refusal",
    [
        httpx.Response(422, text="Unprocessable"),
        httpx.Response(422, json=["invoice_unavailable"]),
    ],
    ids=["not json at all", "json that is not an object"],
)
async def test_a_refusal_in_an_unexpected_shape_is_still_a_refusal(
    refusal: httpx.Response, shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.post("/invoices/generate").mock(return_value=refusal)

    with pytest.raises(InvoiceUnavailableError):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")


async def test_an_invoice_with_no_id_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.post("/invoices/generate").respond(200, json=without(invoice_payload(), "invoice_id"))

    with pytest.raises(UpstreamError):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")


async def test_a_request_shipbob_refuses_outright_is_reported_once(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    route = shipbob.post("/invoices/generate").respond(400, json={"error": "invalid_request"})

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).generate_invoice(
            shipment_id="342578703", user_id="334430"
        )

    assert route.call_count == 1


async def test_a_failure_tells_the_caller_nothing_internal(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json={})

    with pytest.raises(UpstreamError) as raised:
        await build_client(http).list_attachments("CASE-1003")

    failure = raised.value
    assert failure.details == {"resource": "attachment list", "case_id": "CASE-1003"}
    assert failure.message == "The attachment list ShipBob returned could not be read."
    for internal_detail in ("attachments", "validation error", "pydantic", "Traceback", "http"):
        assert internal_detail not in failure.message


async def test_a_failure_never_repeats_the_address_it_was_reading(
    shipbob: respx.Router, settings: Settings
) -> None:
    shipbob.get("/cases/CASE-1003/attachments").mock(side_effect=httpx.ConnectError("refused"))
    address_with_password = settings.shipbob_base_url.replace("http://", "http://reader:hunter2@")

    async with httpx.AsyncClient(base_url=address_with_password, timeout=1.0) as http:
        with pytest.raises(UpstreamError) as raised:
            await build_client(http).list_attachments("CASE-1003")

    assert "hunter2" not in raised.value.message
    assert "hunter2" not in str(raised.value.details)


async def test_closing_the_client_closes_its_connections(settings: Settings) -> None:
    http = httpx.AsyncClient(base_url=settings.shipbob_base_url)

    await EvidenceClient(http).aclose()

    assert http.is_closed


def test_the_client_can_only_read_evidence() -> None:
    reachable = {name for name in dir(EvidenceClient) if not name.startswith("_")}

    assert reachable == {"list_attachments", "generate_invoice", "aclose"}


async def test_an_invoice_for_a_different_shipment_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    shipbob.post("/invoices/generate").respond(
        200, json=invoice_payload(shipment_id="999000111", invoice_id="INV-999000111")
    )

    with pytest.raises(UpstreamError, match="different shipment"):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")
