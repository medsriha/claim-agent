from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
    CONSTRUCTED_INSURED_SUBCATEGORY_ORDER,
    CONSTRUCTED_INSURED_SUBCATEGORY_SHIPMENT,
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

from claim_agent.app import create_app
from claim_agent.domain.models import MerchantCorrection
from claim_agent.settings import Settings
from claim_agent.storage.merchant_memory import MerchantMemory

pytestmark = pytest.mark.integration


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
    mock_shipbob(shipbob, case=case, shipment=shipment, order=order)

    response = await client.post(f"/cases/{case['case_id']}/preflight")

    assert response.status_code == 200
    assert response.json()["verdict"] == expected_verdict


async def test_a_case_with_no_evidence_still_proceeds(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1005, shipment=SHIPMENT_1005, order=ORDER_1005)

    response = await client.post("/cases/CASE-1005/preflight")

    assert response.status_code == 200
    assert response.json()["verdict"] == "proceed"
    assert response.json()["terminal_reasons"] == []


async def test_a_carrier_suffix_on_the_handled_claim_type_still_proceeds(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    carrier_specific_case = {
        **CASE_1001,
        "sub_category": "Claim | Damaged in Transit by USPS",
    }
    mock_shipbob(
        shipbob,
        case=carrier_specific_case,
        shipment=SHIPMENT_1001,
        order=ORDER_1001,
    )

    response = await client.post("/cases/CASE-1001/preflight")

    assert response.status_code == 200
    assert response.json()["verdict"] == "proceed"
    assert response.json()["terminal_reasons"] == []


async def test_an_insured_claim_type_routes_out_when_the_shipment_flag_is_false(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(
        shipbob,
        case=CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
        shipment=CONSTRUCTED_INSURED_SUBCATEGORY_SHIPMENT,
        order=CONSTRUCTED_INSURED_SUBCATEGORY_ORDER,
    )

    response = await client.post("/cases/CASE-9003/preflight")
    body = response.json()

    assert response.status_code == 200
    assert body["verdict"] == "terminal"
    assert body["terminal_reasons"] == ["shipment_insured"]
    assert body["report"]["requires_rep_clarification"] is True
    assert body["report"]["drafted_email"] is None

    insurance_gate = next(gate for gate in body["gates"] if gate["gate"] == "insurance")
    assert insurance_gate["observed"]["is_insured"] == "no"
    assert insurance_gate["observed"]["claim_type_indicates_insured"] == "yes"


async def test_a_stopped_claim_is_a_success_with_a_report_and_an_email(
    app: FastAPI, client: AsyncClient, shipbob: respx.Router
) -> None:
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

    email_body = report["drafted_email"]["body"]
    assert "73 days" in email_body
    assert f"{app.state.live_policy.current().max_claim_age_days} days" in email_body
    assert report["drafted_email"]["is_draft"] is True


async def test_a_claim_allowed_through_carries_no_reasons_and_no_report(
    client: AsyncClient, shipbob: respx.Router
) -> None:
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
    shipbob.get("/cases/CASE-9999").respond(404, json=NOT_FOUND_BODY)

    response = await client.post("/cases/CASE-9999/preflight")
    body = response.json()

    assert response.status_code == 404
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "not_found"


async def test_an_unreachable_shipbob_is_reported_without_leaking_internals(
    client: AsyncClient, shipbob: respx.Router
) -> None:
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
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client.post("/cases/CASE-1001/preflight")

    assert response.headers["X-Request-ID"]


async def test_the_order_value_keeps_its_cents_on_the_wire(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client.post("/cases/CASE-1001/preflight")
    order_value = response.json()["context"]["order_value_usd"]

    assert order_value == "90.00"
    assert isinstance(order_value, str)


@pytest.fixture
def remembered_correction() -> MerchantCorrection:
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
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    response = await client_with_merchant_history.post("/cases/CASE-1001/preflight")
    corrections = response.json()["context"]["merchant_corrections"]

    assert response.status_code == 200
    assert [correction["summary"] for correction in corrections] == [remembered_correction.summary]
    assert corrections[0]["case_id"] == "CASE-1000"
