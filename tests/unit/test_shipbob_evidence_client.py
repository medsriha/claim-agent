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
    """An HTTP client aimed at the stand-in ShipBob, built the way the application builds one.

    The client under test never makes its own, so this is what a caller has to supply.
    """
    async with httpx.AsyncClient(
        base_url=settings.shipbob_base_url,
        timeout=settings.shipbob_timeout_seconds,
    ) as client:
        yield client


def build_client(http: httpx.AsyncClient, *, max_attempts: int = 1) -> EvidenceClient:
    """Build the client under test, with retrying switched off unless a test asks for it.

    A test that is not about retrying should not sit through the waits between attempts,
    so one attempt is the default here even though the application uses three.
    """
    return EvidenceClient(http, max_attempts=max_attempts)


async def test_listing_attachments_gives_back_the_images_on_the_case(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.4: the images are the evidence, and they arrive in the order ShipBob listed them."""
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json=ATTACHMENTS_1003)

    attachments = await build_client(http).list_attachments("CASE-1003")

    assert [attachment.attachment_id for attachment in attachments] == [
        "ATT-CASE-1003-01",
        "ATT-CASE-1003-02",
        "ATT-CASE-1003-03",
    ]
    # A real ShipBob attachment link is a signed Azure URL, so the file name sits in the
    # middle of it rather than at the end. Asserted as a fragment for that reason, not
    # because the assertion was loosened to fit.
    assert "/case-1003/01_Inv.png?" in attachments[0].url


async def test_a_file_name_and_type_are_carried_and_nothing_is_read_into_them(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.4: what an image shows can only be settled by looking at it.

    The first of these attachments is named `Inv.png` and the other two have names fifteen
    seconds apart, yet they are different kinds of evidence. Both fields are passed
    through untouched so that a later step can look at the image itself.
    """
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json=ATTACHMENTS_1003)

    attachments = await build_client(http).list_attachments("CASE-1003")

    assert attachments[0].file_name == "Inv.png"
    assert {attachment.content_type for attachment in attachments} == {"image/png"}


async def test_a_case_with_no_attachments_is_an_ordinary_answer(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.6: no evidence is a finding about the claim, not a failure of the read.

    CASE-1005 has no attachments at all. It has to come back as an empty result so the
    claim can end in a request for information, rather than as an error a rep cannot act
    on.
    """
    shipbob.get("/cases/CASE-1005/attachments").respond(200, json=ATTACHMENTS_1005)

    attachments = await build_client(http).list_attachments("CASE-1005")

    assert attachments == ()


async def test_attachments_for_a_case_that_does_not_exist_are_reported_once(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.6, NFR-6: "there is no such case" is a real answer, so asking twice wastes time.

    It is also emphatically not the same answer as "this case has no attachments", which
    is why it raises rather than coming back as an empty result.
    """
    route = shipbob.get("/cases/CASE-9999/attachments").respond(404, json=CASE_NOT_FOUND_BODY)

    with pytest.raises(NotFoundError):
        await build_client(http, max_attempts=3).list_attachments("CASE-9999")

    assert route.call_count == 1


async def test_an_unreachable_shipbob_is_tried_again_and_then_reported(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a claim is not lost to one slow moment, but nor does a read go on forever."""
    route = shipbob.get("/cases/CASE-1003/attachments").mock(
        side_effect=httpx.TimeoutException("too slow")
    )

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).list_attachments("CASE-1003")

    assert route.call_count == 3


async def test_a_momentary_failure_at_shipbob_is_survived(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: ShipBob reporting a fault of its own is worth trying again.

    Tried on the invoice, which is the one call that sends a request body, so a retry is
    shown to send the whole request again rather than an empty one.
    """
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
    """NFR-4, NFR-6: a page of HTML from a proxy is a failure, not a list of evidence."""
    route = shipbob.get("/cases/CASE-1003/attachments").respond(
        200, text="<html>Service unavailable</html>", content_type="text/html"
    )

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).list_attachments("CASE-1003")

    assert route.call_count == 1


async def test_a_reply_that_never_mentions_attachments_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.6, NFR-4: a reply we could not read must never pass as "this merchant sent nothing".

    An empty list is a finding; a missing list is a broken reply. Treating the second as
    the first would tell a rep a merchant supplied no evidence when in truth nobody knows.
    """
    shipbob.get("/cases/CASE-1003/attachments").respond(200, json={})

    with pytest.raises(UpstreamError):
        await build_client(http).list_attachments("CASE-1003")


async def test_an_attachment_with_no_address_to_fetch_it_from_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an image nobody can fetch cannot be part of a listing that says it is there."""
    shipbob.get("/cases/CASE-1003/attachments").respond(
        200, json=attachments_payload(without(attachment_payload(), "url"))
    )

    with pytest.raises(UpstreamError):
        await build_client(http).list_attachments("CASE-1003")


async def test_an_unusual_case_id_cannot_reach_a_different_address(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a case id is one part of an address and is never allowed to become more of it."""
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
    """FR-1.18: the invoice is the only thing a recommended amount may be worked out from."""
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
    """FR-1.18, NFR-2: $38.00 has to stay $38.00, so no amount rests on an approximation."""
    # Written out by hand rather than built from a dictionary: turning a dictionary into
    # JSON in Python writes 38.00 as `38.0`, which is the very thing this test is here to
    # notice. This is what ShipBob actually sends.
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
    # An exact decimal, so never a floating point number: the two share no common ground,
    # and the type checker refuses even to let this test ask whether it is a float.
    assert isinstance(unit_price, Decimal)
    # Two decimal places, still. `Decimal("38.0")` — what a float on the way through
    # produces — would pass the equality check above and fail both of these.
    assert str(unit_price) == "38.00"
    assert unit_price.as_tuple().exponent == -2


async def test_shipbob_refusing_to_price_a_shipment_is_its_own_answer(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.18: "I will not price this" is a settled answer, not ShipBob being broken.

    The two have to be told apart. This one sends the claim to a rep with a reason to
    give; an outage is a fault that may pass. A caller that saw them as one failure would
    report one as the other.
    """
    shipbob.post("/invoices/generate").respond(422, json=INVOICE_UNAVAILABLE_BODY)

    with pytest.raises(InvoiceUnavailableError) as raised:
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")

    failure = raised.value
    # Not a kind of upstream failure, because the retry rule asks again on any of those
    # and this is the one reply where asking again only wastes a claim's time.
    assert not isinstance(failure, UpstreamError)
    assert failure.code == "invoice_unavailable"
    # The code is what a caller branches on. The status is deliberately not ShipBob's
    # own 422: that is what FastAPI itself returns for a malformed request, and the two
    # would be confused if this ever travelled out of the API — which it should not,
    # since an investigation turns it into an representative clarification request long before then.
    assert failure.status_code == 502
    assert failure.details == {"resource": "invoice", "shipment_id": "342578703"}


async def test_a_shipment_shipbob_will_not_price_is_not_asked_about_again(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.18, NFR-6: a refusal aimed at this one request will be refused again next time."""
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
    """FR-1.18, NFR-6: nothing is decided from the short code, so a reply without one still works.

    REQUIREMENTS.md names the code ShipBob sends but does not print the reply it arrives
    in, so the shape our code looks for is a guess. The refusal has to stand whether the
    guess is right or not — the status is what settles it, and the code only ever reaches
    the logs.
    """
    shipbob.post("/invoices/generate").mock(return_value=refusal)

    with pytest.raises(InvoiceUnavailableError):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")


async def test_an_invoice_with_no_id_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: an invoice a finding cannot name is not an invoice we can price a claim from."""
    shipbob.post("/invoices/generate").respond(200, json=without(invoice_payload(), "invoice_id"))

    with pytest.raises(UpstreamError):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")


async def test_a_request_shipbob_refuses_outright_is_reported_once(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: a request ShipBob will not accept will not be accepted the second time either."""
    route = shipbob.post("/invoices/generate").respond(400, json={"error": "invalid_request"})

    with pytest.raises(UpstreamError):
        await build_client(http, max_attempts=3).generate_invoice(
            shipment_id="342578703", user_id="334430"
        )

    assert route.call_count == 1


async def test_a_failure_tells_the_caller_nothing_internal(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """NFR-6: the reason a reply was rejected goes to the logs; the caller gets a sentence."""
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
    """NFR-6: the ShipBob address may carry a password, so no message or detail may quote it."""
    shipbob.get("/cases/CASE-1003/attachments").mock(side_effect=httpx.ConnectError("refused"))
    address_with_password = settings.shipbob_base_url.replace("http://", "http://reader:hunter2@")

    async with httpx.AsyncClient(base_url=address_with_password, timeout=1.0) as http:
        with pytest.raises(UpstreamError) as raised:
            await build_client(http).list_attachments("CASE-1003")

    assert "hunter2" not in raised.value.message
    assert "hunter2" not in str(raised.value.details)


async def test_closing_the_client_closes_its_connections(settings: Settings) -> None:
    """NFR-6: a caller holding only this client can still shut it down tidily."""
    http = httpx.AsyncClient(base_url=settings.shipbob_base_url)

    await EvidenceClient(http).aclose()

    assert http.is_closed


def test_the_client_can_only_read_evidence() -> None:
    """FR-1.2, NFR-8: emailing a merchant and paying a reimbursement are out of reach.

    The two endpoints an investigation is allowed to use are here, and the two
    irreversible ones are not reachable from it at all. That is a property of the code
    rather than a promise in a comment, which is the whole point of the guarantee.
    """
    reachable = {name for name in dir(EvidenceClient) if not name.startswith("_")}

    assert reachable == {"list_attachments", "generate_invoice", "aclose"}


async def test_an_invoice_for_a_different_shipment_is_refused(
    shipbob: respx.Router, http: httpx.AsyncClient
) -> None:
    """FR-1.18, NFR-4: the invoice is the only thing a payout may be priced from.

    So it has to be an invoice for the shipment we asked about. REQUIREMENTS.md is
    explicit that a well-formed reply from this API is not evidence of correctness — the
    reimbursement endpoint approves every request put to it, including claims the system
    decided to deny — so a reply is checked against what was asked for rather than
    trusted for having arrived. Without this, a mismatched invoice would quietly price a
    claim from another shipment's products.
    """
    shipbob.post("/invoices/generate").respond(
        200, json=invoice_payload(shipment_id="999000111", invoice_id="INV-999000111")
    )

    with pytest.raises(UpstreamError, match="different shipment"):
        await build_client(http).generate_invoice(shipment_id="342578703", user_id="334430")
