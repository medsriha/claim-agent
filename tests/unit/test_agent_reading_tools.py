"""The four reading tools added after studying ShipBob's sample data.

No requirement asks for any of them, so these tests name the nearest ones: the dollar
cap (FR-1.20), never narrowing two candidates to one (FR-1.13), the same answer twice
(NFR-1), and a failure ending in front of a person (NFR-4).
"""

from __future__ import annotations

import httpx
import pytest
import respx
from tests.fakes.model import ScriptedModel
from tests.fixtures.attachments import INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, CASE_1003, SHIPMENT_1001, SHIPMENT_1003

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventStream
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.tools import (
    CHECK_CURRENCY,
    CHECK_DOCUMENT_TOTALS,
    COMPARE_PRICES,
    READ_CASE_FACTS,
    CaseFactsReading,
    CurrencyCheck,
    DocumentTotalsCheck,
    PriceComparison,
    ReceiptLineArgument,
    investigation_tools,
)
from claim_agent.domain.models import Case, Shipment
from claim_agent.policy import Policy
from claim_agent.shipbob.evidence_client import EvidenceClient

SHIPBOB = "http://shipbob.test"


def tools_for(
    http: httpx.AsyncClient,
    *,
    case: dict[str, object] = CASE_1001,
    shipment: dict[str, object] | None = SHIPMENT_1001,
    policy: Policy | None = None,
) -> dict[str, object]:
    """Build the tool set for one claim, indexed by name so a test can pick one out."""
    record = Case.model_validate(case)
    parcel = None if shipment is None else Shipment.model_validate(shipment)
    built = investigation_tools(
        case_id=record.case_id,
        shipment_id=record.shipment_id,
        user_id=record.user_id,
        case=record,
        shipment=parcel,
        evidence=EvidenceClient(http, max_attempts=1),
        fetcher=None,  # type: ignore[arg-type]
        model=StructuredModel(ScriptedModel(replies=[]), max_attempts=1),
        cache=ObservationCache(),
        budget=RunBudget(policy or Policy()),
        ledger=RunLedger(),
        events=EventStream(),
        policy=policy or Policy(),
    )
    return {tool.name: tool for tool in built}


async def call(tool: object, **arguments: object) -> object:
    """Invoke one tool and hand back the outcome it kept beside its sentence."""
    _, outcome = await tool.coroutine(**arguments)  # type: ignore[attr-defined]
    return outcome


# --- Currency ---------------------------------------------------------------


async def test_case_1001_is_read_as_pounds_from_its_carrier_and_tracking_number() -> None:
    """FR-1.20: the real CASE-1001 ships Royal Mail on a GB tracking number.

    ShipBob's records say nothing about currency, so without this the claim's 90.00 is
    measured against a dollar cap it may well be over.
    """
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(tools_for(http)[CHECK_CURRENCY], symbols_seen=("£",))

    assert isinstance(outcome, CurrencyCheck)
    assert outcome.currency == "GBP"
    assert outcome.is_ambiguous is False


async def test_ninety_pounds_converts_to_more_than_the_hundred_dollar_cap() -> None:
    """FR-1.20: the figure that is inside the cap as dollars and outside it as pounds."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(tools_for(http)[CHECK_CURRENCY], symbols_seen=("£",), amount="90.00")

    assert isinstance(outcome, CurrencyCheck)
    assert outcome.usd_amount == "114.30"
    assert outcome.rates_as_of == "2026-09-04"


async def test_two_clues_that_disagree_settle_nothing() -> None:
    """FR-1.13: a GB parcel showing a dollar sign is a puzzle, not a conclusion."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(tools_for(http)[CHECK_CURRENCY], symbols_seen=("$",))

    assert isinstance(outcome, CurrencyCheck)
    assert outcome.currency is None
    assert outcome.is_ambiguous is True


async def test_an_amount_that_cannot_be_read_is_refused_rather_than_guessed() -> None:
    """NFR-4: a figure read wrongly is worse than one not read at all."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[CHECK_CURRENCY], symbols_seen=("£",), amount="about ninety"
        )

    assert isinstance(outcome, CurrencyCheck)
    assert outcome.succeeded is False
    assert outcome.usd_amount is None


async def test_a_claim_with_no_shipment_record_still_answers() -> None:
    """NFR-4: no clues at all is an ordinary answer, not a failure."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(tools_for(http, shipment=None)[CHECK_CURRENCY])

    assert isinstance(outcome, CurrencyCheck)
    assert outcome.succeeded is True
    assert outcome.currency is None


# --- A document's own arithmetic --------------------------------------------


async def test_case_1002_sales_order_is_caught_disagreeing_with_itself() -> None:
    """The real CASE-1002 document: 9.95 + 16.99 + 19.99 is 46.93, not the 49.85 printed."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[CHECK_DOCUMENT_TOTALS],
            line_amounts=("$9.95", "$16.99", "$19.99"),
            subtotal="$49.85",
            tax="$0.00",
            total="$49.42",
        )

    assert isinstance(outcome, DocumentTotalsCheck)
    assert outcome.is_consistent is False
    assert outcome.line_total == "46.93"
    assert outcome.disagreements


async def test_a_document_that_adds_up_is_left_alone() -> None:
    """The real CASE-1003 invoice: 149.98 of items less a 14.99 discount is 134.99."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[CHECK_DOCUMENT_TOTALS],
            line_amounts=("$35.96", "$42.45", "$41.21", "$30.36"),
            subtotal="$149.98",
            discount="$14.99",
            total="$134.99",
        )

    assert isinstance(outcome, DocumentTotalsCheck)
    assert outcome.is_consistent is True
    assert outcome.disagreements == ()


async def test_a_figure_that_cannot_be_read_is_listed_rather_than_guessed() -> None:
    """NFR-4: the run has to be able to see that its picture of the document is partial."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[CHECK_DOCUMENT_TOTALS],
            line_amounts=("$9.95", "1.234"),
            total="$9.95",
        )

    assert isinstance(outcome, DocumentTotalsCheck)
    assert len(outcome.unreadable_figures) == 1


# --- The claim's own description --------------------------------------------


async def test_case_1003_description_contradicts_shipbobs_records() -> None:
    """The real CASE-1003 says `Carrier: Other` and two affected orders; ShipBob says USPS."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http, case=CASE_1003, shipment=SHIPMENT_1003)[READ_CASE_FACTS]
        )

    assert isinstance(outcome, CaseFactsReading)
    assert outcome.affected_order_count == 2
    assert outcome.contradictions


async def test_a_claim_whose_case_record_is_missing_says_so_rather_than_failing() -> None:
    """NFR-4: the tool answers, and the run carries on."""
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        tools = investigation_tools(
            case_id="CASE-1001",
            shipment_id=None,
            user_id=None,
            case=None,
            shipment=None,
            evidence=EvidenceClient(http, max_attempts=1),
            fetcher=None,  # type: ignore[arg-type]
            model=StructuredModel(ScriptedModel(replies=[]), max_attempts=1),
            cache=ObservationCache(),
            budget=RunBudget(Policy()),
            ledger=RunLedger(),
            events=EventStream(),
            policy=Policy(),
        )
        outcome = await call({tool.name: tool for tool in tools}[READ_CASE_FACTS])

    assert isinstance(outcome, CaseFactsReading)
    assert outcome.succeeded is False


# --- ShipBob's prices against the customer's receipt ------------------------


@respx.mock
async def test_shipbobs_price_and_the_customers_receipt_are_both_reported() -> None:
    """The real CASE-1001 invoice totals 90.00; its receipt shows one line at 55.95.

    Neither figure is chosen. Both go in front of a person, because nobody has decided
    which of the two a claim is priced from.
    """
    respx.post(f"{SHIPBOB}/invoices/generate").respond(200, json=INVOICE_342578703)
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[COMPARE_PRICES],
            receipt_lines=(
                ReceiptLineArgument(description="Liposomal Tripeptide Collagen", amount="55.95"),
            ),
            receipt_total="55.95",
        )

    assert isinstance(outcome, PriceComparison)
    assert outcome.shipbob_total == "90.00"
    assert outcome.receipt_total == "55.95"
    assert outcome.line_counts_differ is True


@respx.mock
async def test_a_shipment_that_cannot_be_priced_is_an_answer_not_an_error() -> None:
    """NFR-4: ShipBob refusing to price a shipment must not stop the investigation."""
    respx.post(f"{SHIPBOB}/invoices/generate").respond(422, json={"error": "invoice_unavailable"})
    async with httpx.AsyncClient(base_url=SHIPBOB) as http:
        outcome = await call(
            tools_for(http)[COMPARE_PRICES],
            receipt_lines=(ReceiptLineArgument(description="anything", amount="10.00"),),
        )

    assert isinstance(outcome, PriceComparison)
    assert outcome.succeeded is False


@pytest.mark.parametrize("tool_name", [CHECK_CURRENCY, CHECK_DOCUMENT_TOTALS, READ_CASE_FACTS])
async def test_no_reading_tool_is_named_for_something_that_changes_anything(
    tool_name: str,
) -> None:
    """FR-1.2: the guarantee is that nothing here writes, whatever the tool count is."""
    assert not any(
        word in tool_name for word in ("send", "submit", "pay", "email", "reimburse", "create")
    )
