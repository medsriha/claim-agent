from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1004,
    NOT_FOUND_BODY,
    ORDER_1001,
    ORDER_1004,
    SHIPMENT_1001,
    SHIPMENT_1004,
    case_payload,
    mock_shipbob,
    order_payload,
    shipment_payload,
    without,
)

from claim_agent.domain.models import GateName, MerchantCorrection, TerminalReason, Verdict
from claim_agent.errors import NotFoundError, StorageError, UpstreamError
from claim_agent.policy import Policy
from claim_agent.preflight.gather import gather_case_record
from claim_agent.preflight.models import PreflightResult
from claim_agent.preflight.service import run_preflight
from claim_agent.settings import Settings
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.storage.merchant_memory import MerchantMemory

EVALUATED_AT = datetime(2026, 3, 10, 9, 0, 0, tzinfo=UTC)
A_DECADE_LATER = datetime(2036, 3, 10, 9, 0, 0, tzinfo=UTC)


BEST_PAW_NUTRITION = "334430"
CLEANBOSS = "283959"


EVERYTHING_WRONG_CASE = case_payload(
    case_id="CASE-9101",
    sub_category="Claim | Lost in Transit",
    description=None,
    order_id="990000101",
    user_id="990000101",
    shipment_id="990000101",
    delivered_date="2025-12-26T12:13:36.000+0000",
    contact_email="claims@constructed-four-failures.example.com",
    account_name="Constructed Four Failures Merchant",
    created_date="2026-03-09T18:51:42.000+0000",
)
EVERYTHING_WRONG_SHIPMENT = shipment_payload(
    shipment_id="990000101",
    order_id="990000101",
    delivered_date="2025-12-26T12:13:36.000+0000",
    is_insured=True,
)
EVERYTHING_WRONG_ORDER = order_payload(order_id="990000101", user_id="990000101")


@pytest.fixture
async def http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=settings.shipbob_base_url,
        timeout=settings.shipbob_timeout_seconds,
    ) as client:
        yield client


@pytest.fixture
def shipbob_client(http: httpx.AsyncClient) -> ShipBobClient:
    return ShipBobClient(http, max_attempts=1)


@pytest.fixture
def memory(settings: Settings) -> MerchantMemory:
    return MerchantMemory(settings.database_path)


async def screen(
    case_id: str,
    client: ShipBobClient,
    memory: MerchantMemory,
    evaluated_at: datetime = EVALUATED_AT,
) -> PreflightResult:
    return await run_preflight(
        case_id=case_id,
        client=client,
        memory=memory,
        policy=Policy(),
        evaluated_at=evaluated_at,
    )


def a_correction(user_id: str, case_id: str, summary: str) -> MerchantCorrection:
    return MerchantCorrection(
        user_id=user_id,
        case_id=case_id,
        summary=summary,
        recorded_at=datetime(2026, 2, 20, 10, 30, 0, tzinfo=UTC),
    )


async def test_gathering_reads_the_case_the_shipment_and_the_order_once_each(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    case_route = shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipment_route = shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    order_route = shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)

    record = await gather_case_record("CASE-1001", shipbob_client)

    assert case_route.call_count == 1
    assert shipment_route.call_count == 1
    assert order_route.call_count == 1
    assert record.case.case_id == "CASE-1001"
    assert record.shipment is not None
    assert record.order is not None


async def test_a_shipment_shipbob_does_not_have_is_left_empty_instead_of_failing(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=None, order=ORDER_1001)

    record = await gather_case_record("CASE-1001", shipbob_client)

    assert record.shipment is None
    assert record.order is not None


async def test_an_order_shipbob_does_not_have_is_left_empty_instead_of_failing(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=None)

    record = await gather_case_record("CASE-1001", shipbob_client)

    assert record.order is None
    assert record.shipment is not None


async def test_shipbob_failing_on_the_shipment_stops_the_claim_rather_than_emptying_it(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    mock_shipbob(
        shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001, shipment_status=500
    )

    with pytest.raises(UpstreamError):
        await gather_case_record("CASE-1001", shipbob_client)


async def test_shipbob_timing_out_on_the_shipment_stops_the_claim_rather_than_emptying_it(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/shipments/342578703").mock(
        side_effect=httpx.TimeoutException("ShipBob took too long")
    )

    with pytest.raises(UpstreamError):
        await gather_case_record("CASE-1001", shipbob_client)


async def test_shipbob_failing_on_the_order_stops_the_claim_rather_than_emptying_it(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    mock_shipbob(
        shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001, order_status=503
    )

    with pytest.raises(UpstreamError):
        await gather_case_record("CASE-1001", shipbob_client)


async def test_a_case_shipbob_does_not_have_is_reported_as_not_found(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    shipbob.get("/cases/CASE-9999").respond(404, json=NOT_FOUND_BODY)

    with pytest.raises(NotFoundError):
        await gather_case_record("CASE-9999", shipbob_client)


async def test_a_case_naming_no_shipment_never_asks_shipbob_for_one(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    case = without(CASE_1001, "shipment_id")
    shipbob.get("/cases/CASE-1001").respond(200, json=case)
    shipment_route = shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)

    record = await gather_case_record("CASE-1001", shipbob_client)

    assert not shipment_route.called
    assert record.shipment is None


async def test_a_case_naming_no_order_never_asks_shipbob_for_one(
    shipbob: respx.Router, shipbob_client: ShipBobClient
) -> None:
    case = without(CASE_1001, "order_id")
    shipbob.get("/cases/CASE-1001").respond(200, json=case)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    order_route = shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)

    record = await gather_case_record("CASE-1001", shipbob_client)

    assert not order_route.called
    assert record.order is None


async def test_a_claim_that_clears_every_check_carries_on(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    result = await screen("CASE-1001", shipbob_client, memory)

    assert result.verdict is Verdict.PROCEED
    assert result.terminal_reasons == ()
    assert result.report is None
    assert all(gate.passed for gate in result.gates)


async def test_a_claim_filed_too_late_is_stopped_and_written_up_for_a_rep(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)

    result = await screen("CASE-1004", shipbob_client, memory)

    assert result.verdict is Verdict.TERMINAL
    assert result.terminal_reasons == (TerminalReason.CLAIM_TOO_OLD,)
    assert result.report is not None
    assert result.report.case_id == "CASE-1004"
    assert result.report.requires_rep_approval is True

    assert result.report.requires_rep_clarification is False
    assert result.report.drafted_email is not None
    assert result.report.drafted_email.to == "sakukreja+6@shipbob.com"
    assert result.report.drafted_email.subject
    assert result.report.drafted_email.body


async def test_a_claim_that_fails_several_checks_lists_every_reason_in_order(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(
        shipbob,
        case=EVERYTHING_WRONG_CASE,
        shipment=EVERYTHING_WRONG_SHIPMENT,
        order=EVERYTHING_WRONG_ORDER,
    )

    result = await screen("CASE-9101", shipbob_client, memory)

    assert result.verdict is Verdict.TERMINAL
    assert result.terminal_reasons == (
        TerminalReason.SHIPMENT_INSURED,
        TerminalReason.CLAIM_TOO_OLD,
        TerminalReason.WRONG_CLAIM_TYPE,
        TerminalReason.MISSING_KEY_INFORMATION,
    )
    assert result.report is not None
    assert len(result.report.findings) == 4


@pytest.mark.parametrize(
    ("case", "shipment", "order"),
    [
        pytest.param(CASE_1001, SHIPMENT_1001, ORDER_1001, id="a claim that carries on"),
        pytest.param(CASE_1004, SHIPMENT_1004, ORDER_1004, id="a claim that is stopped"),
    ],
)
async def test_all_four_checks_are_reported_whichever_way_the_verdict_went(
    shipbob: respx.Router,
    shipbob_client: ShipBobClient,
    memory: MerchantMemory,
    case: dict[str, object],
    shipment: dict[str, object],
    order: dict[str, object],
) -> None:
    mock_shipbob(shipbob, case=case, shipment=shipment, order=order)

    result = await screen(str(case["case_id"]), shipbob_client, memory)

    assert tuple(gate.gate for gate in result.gates) == (
        GateName.AGE,
        GateName.CLAIM_TYPE,
        GateName.KEY_INFORMATION,
        GateName.INSURANCE,
    )


async def test_what_a_rep_corrected_for_this_merchant_before_reaches_the_claim(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    memory.record_correction(
        a_correction(
            BEST_PAW_NUTRITION,
            "CASE-0900",
            "Rep paid for the ampoule duo only; the collagen was undamaged.",
        )
    )
    memory.record_correction(
        a_correction(CLEANBOSS, "CASE-0901", "Rep reduced the claim to one bottle.")
    )
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    result = await screen("CASE-1001", shipbob_client, memory)

    assert len(result.context.merchant_corrections) == 1
    assert result.context.merchant_corrections[0].case_id == "CASE-0900"


async def test_another_merchants_corrections_never_reach_this_claim(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    memory.record_correction(
        a_correction(CLEANBOSS, "CASE-0901", "Rep reduced the claim to one bottle.")
    )
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    result = await screen("CASE-1001", shipbob_client, memory)

    assert result.context.merchant_corrections == ()


async def test_a_case_naming_no_merchant_is_screened_anyway_with_nothing_remembered(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    memory.record_correction(
        a_correction(BEST_PAW_NUTRITION, "CASE-0900", "Rep paid for the ampoule duo only.")
    )
    case = without(CASE_1001, "user_id")
    mock_shipbob(shipbob, case=case, shipment=SHIPMENT_1001, order=ORDER_1001)

    result = await screen("CASE-1001", shipbob_client, memory)

    assert result.verdict is Verdict.PROCEED
    assert result.context.merchant_corrections == ()


async def test_a_store_we_cannot_read_stops_the_screen_rather_than_guessing_at_it(
    shipbob: respx.Router,
    shipbob_client: ShipBobClient,
    tmp_path: Path,
) -> None:
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)
    unreadable = tmp_path / "corrupt.db"
    unreadable.write_bytes(b"this file is not a database")

    with pytest.raises(StorageError) as failure:
        await screen("CASE-1004", shipbob_client, MerchantMemory(unreadable))

    assert failure.value.code == "storage_unavailable"


async def test_screening_the_same_claim_twice_gives_exactly_the_same_answer(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)

    first = await screen("CASE-1004", shipbob_client, memory)
    second = await screen("CASE-1004", shipbob_client, memory)

    assert first == second


async def test_screening_a_claim_a_decade_later_gives_the_same_answer(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)

    today = await screen("CASE-1004", shipbob_client, memory, EVALUATED_AT)
    much_later = await screen("CASE-1004", shipbob_client, memory, A_DECADE_LATER)

    assert today.model_dump(mode="json", exclude={"evaluated_at"}) == much_later.model_dump(
        mode="json", exclude={"evaluated_at"}
    )
    assert today.evaluated_at != much_later.evaluated_at


async def test_the_answer_writes_itself_out_byte_for_byte_the_same_every_time(
    shipbob: respx.Router, shipbob_client: ShipBobClient, memory: MerchantMemory
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    first = await screen("CASE-1001", shipbob_client, memory)
    second = await screen("CASE-1001", shipbob_client, memory)

    assert first.model_dump_json().encode("utf-8") == second.model_dump_json().encode("utf-8")


@pytest.mark.parametrize(
    ("case", "shipment", "order"),
    [
        pytest.param(CASE_1001, SHIPMENT_1001, ORDER_1001, id="a claim that carries on"),
        pytest.param(CASE_1004, SHIPMENT_1004, ORDER_1004, id="a claim that is stopped"),
    ],
)
async def test_the_screen_never_asks_for_a_claims_attachments(
    shipbob: respx.Router,
    shipbob_client: ShipBobClient,
    memory: MerchantMemory,
    case: dict[str, object],
    shipment: dict[str, object],
    order: dict[str, object],
) -> None:
    mock_shipbob(shipbob, case=case, shipment=shipment, order=order)
    attachments = shipbob.get(f"/cases/{case['case_id']}/attachments").respond(200, json={})

    await screen(str(case["case_id"]), shipbob_client, memory)

    assert not attachments.called


@pytest.mark.parametrize(
    ("case", "shipment", "order"),
    [
        pytest.param(CASE_1001, SHIPMENT_1001, ORDER_1001, id="a claim that carries on"),
        pytest.param(CASE_1004, SHIPMENT_1004, ORDER_1004, id="a claim that is stopped"),
    ],
)
async def test_the_screen_never_asks_an_ai_anything(
    shipbob: respx.Router,
    shipbob_client: ShipBobClient,
    memory: MerchantMemory,
    case: dict[str, object],
    shipment: dict[str, object],
    order: dict[str, object],
) -> None:
    mock_shipbob(shipbob, case=case, shipment=shipment, order=order)
    anthropic = shipbob.route(host="api.anthropic.com").respond(200, json={})

    await screen(str(case["case_id"]), shipbob_client, memory)

    assert not anthropic.called
