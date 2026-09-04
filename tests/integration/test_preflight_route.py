"""Screening a claim through the HTTP surface (FR-0.1 to FR-0.6).

Every request in this file is answered by a stand-in ShipBob running in the same
process, so nothing reaches the network. What these tests care about is what a
caller actually receives: the status code, the shape of the body, and the exact
text of the values in it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from claim_agent.app import create_app
from claim_agent.domain.models import MerchantCorrection
from claim_agent.settings import Settings
from claim_agent.storage.merchant_memory import MerchantMemory
from fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    NOT_FOUND_BODY,
    ORDER_1001,
    ORDER_1002,
    ORDER_1003,
    ORDER_1004,
    ORDER_1005,
    SHIPMENT_1001,
    SHIPMENT_1002,
    SHIPMENT_1003,
    SHIPMENT_1004,
    SHIPMENT_1005,
    mock_shipbob,
)

pytestmark = pytest.mark.integration

# CASE-1001's merchant, the one account number REQUIREMENTS.md ties to a case.
BEST_PAW_NUTRITION = "334430"


@pytest.mark.parametrize(
    ("case", "shipment", "order", "expected_verdict"),
    [
        pytest.param(CASE_1001, SHIPMENT_1001, ORDER_1001, "proceed", id="CASE-1001"),
        pytest.param(CASE_1002, SHIPMENT_1002, ORDER_1002, "proceed", id="CASE-1002"),
        pytest.param(CASE_1003, SHIPMENT_1003, ORDER_1003, "proceed", id="CASE-1003"),
        pytest.param(CASE_1004, SHIPMENT_1004, ORDER_1004, "terminal", id="CASE-1004"),
        pytest.param(CASE_1005, SHIPMENT_1005, ORDER_1005, "proceed", id="CASE-1005"),
    ],
)
async def test_sample_case_verdict(
    client: AsyncClient,
    shipbob: respx.Router,
    case: dict[str, object],
    shipment: dict[str, object],
    order: dict[str, object],
    expected_verdict: str,
) -> None:
    """FR-0.2, FR-0.3: only the claim filed 73 days after delivery is turned away.

    The other four are ordinary uninsured damage claims filed within a week, so
    nothing rules them out and the investigation gets to run.
    """
    mock_shipbob(shipbob, case=case, shipment=shipment, order=order)

    response = await client.post(f"/cases/{case['case_id']}/preflight")

    assert response.status_code == 200
    assert response.json()["verdict"] == expected_verdict


async def test_a_case_with_no_evidence_still_proceeds(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.2: having no photographs is not a reason to turn a claim away.

    CASE-1005 arrives with nothing attached to it at all. That matters, and it is
    deliberately not decided here: whether a claim can be settled without evidence
    is a question for the investigation, which can ask the merchant for photographs.
    The four eligibility checks ask something narrower — is this claim the kind of
    thing we can look into — and a claim with no pictures still is.
    """
    mock_shipbob(shipbob, case=CASE_1005, shipment=SHIPMENT_1005, order=ORDER_1005)

    response = await client.post("/cases/CASE-1005/preflight")

    assert response.status_code == 200
    assert response.json()["verdict"] == "proceed"
    assert response.json()["terminal_reasons"] == []


async def test_a_stopped_claim_is_a_success_with_a_report_and_an_email(
    app: FastAPI, client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.3, FR-0.4: a claim that cannot be processed still comes back as an answer.

    CASE-1004 was delivered on 26 December and filed on 9 March — 73 days — so it is
    past the age limit. Being turned away is a correct screening result rather than a
    failed request, so the status is a success, and the body carries the write-up and
    the merchant email a rep has to approve.
    """
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)

    response = await client.post("/cases/CASE-1004/preflight")
    body = response.json()

    assert response.status_code == 200
    assert body["verdict"] == "terminal"
    assert body["terminal_reasons"] == ["claim_too_old"]

    report = body["report"]
    assert report is not None
    assert report["case_id"] == "CASE-1004"
    assert report["requires_rep_approval"] is True

    # The merchant is told the arithmetic, not just the outcome: how long they waited
    # and how long they had (NFR-3). The limit is read off the running application
    # rather than written in here, because it is a provisional number that may change.
    email_body = report["drafted_email"]["body"]
    assert "73 days" in email_body
    assert f"{app.state.policy.max_claim_age_days} days" in email_body
    assert report["drafted_email"]["is_draft"] is True


async def test_a_claim_allowed_through_carries_no_reasons_and_no_report(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.3: nothing rules CASE-1001 out, so there is nothing for a rep to approve.

    The report exists only to explain a claim that was stopped. A claim on its way to
    the investigation must not carry one, or a rep would be asked to approve closing a
    claim that is still open.
    """
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client.post("/cases/CASE-1001/preflight")
    body = response.json()

    assert response.status_code == 200
    assert body["verdict"] == "proceed"
    assert body["terminal_reasons"] == []
    assert body["report"] is None


async def test_a_case_shipbob_does_not_have_is_reported_as_not_found(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.1, NFR-6: a case id nobody recognises is a handled answer, not a crash."""
    shipbob.get("/cases/CASE-9999").respond(404, json=NOT_FOUND_BODY)

    response = await client.post("/cases/CASE-9999/preflight")
    body = response.json()

    assert response.status_code == 404
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "not_found"


async def test_an_unreachable_shipbob_is_reported_without_leaking_internals(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """NFR-6: ShipBob being down stops the claim visibly, and says nothing private.

    The caller learns that the read failed and which record it was. They do not learn
    which library raised what, or what address we call, because that is our business
    and, in the wrong hands, a map of it.
    """
    shipbob.get("/cases/CASE-1001").mock(
        side_effect=httpx.ConnectError("connection refused"),
    )

    response = await client.post("/cases/CASE-1001/preflight")
    body = response.json()

    assert response.status_code == 502
    assert body["error"]["code"] == "upstream_unavailable"
    assert "connection refused" not in str(body)
    assert "ConnectError" not in str(body)
    assert "shipbob.test" not in str(body)


async def test_the_answer_carries_a_request_id(client: AsyncClient, shipbob: respx.Router) -> None:
    """NFR-5: every answer is tagged, so a claim can be traced back through the logs."""
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client.post("/cases/CASE-1001/preflight")

    assert response.headers["X-Request-ID"]


async def test_the_order_value_keeps_its_cents_on_the_wire(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.5, FR-1.21: money leaves the service as exact text, never as a fraction.

    CASE-1001's order is $38.00 plus $52.00, so the answer has to read "90.00" —
    written out, with its cents, exactly as it was added up. Sent as an ordinary
    number it would arrive as 90.0, and an amount like 0.10 cannot be written as one
    of those at all. This is the last point where that can be lost, so it is checked
    here rather than only where the sum is done.
    """
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client.post("/cases/CASE-1001/preflight")
    order_value = response.json()["context"]["order_value_usd"]

    assert order_value == "90.00"
    assert isinstance(order_value, str)


@pytest.fixture
def remembered_correction() -> MerchantCorrection:
    """One thing a rep changed on an earlier claim from CASE-1001's merchant."""
    return MerchantCorrection(
        user_id=BEST_PAW_NUTRITION,
        case_id="CASE-1000",
        summary="Rep paid for the ampoule duo only; the collagen was undamaged.",
        recorded_at=datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
    )


@pytest.fixture
async def client_with_merchant_history(
    settings: Settings,
    tmp_path: Path,
    remembered_correction: MerchantCorrection,
) -> AsyncIterator[AsyncClient]:
    """An application whose merchant store already holds one correction.

    The store is handed to the application rather than reached into afterwards, and
    it deliberately uses a different file from the one the settings name, so a route
    reading anything other than the store it was given would come back empty.
    """
    memory = MerchantMemory(tmp_path / "seeded.db")
    memory.record_correction(remembered_correction)
    app = create_app(settings, merchant_memory=memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_what_a_rep_corrected_before_reaches_the_next_claim(
    client_with_merchant_history: AsyncClient,
    shipbob: respx.Router,
    remembered_correction: MerchantCorrection,
) -> None:
    """FR-0.5, FR-3.8: the investigation starts knowing what a rep already fixed.

    The point of remembering is that the same correction does not have to be made
    twice, which only works if it travels out with the claim rather than sitting in a
    database nobody reads.
    """
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client_with_merchant_history.post("/cases/CASE-1001/preflight")
    corrections = response.json()["context"]["merchant_corrections"]

    assert response.status_code == 200
    assert [correction["summary"] for correction in corrections] == [remembered_correction.summary]
    assert corrections[0]["case_id"] == "CASE-1000"
