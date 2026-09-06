from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import respx
from langchain_core.messages import AIMessage
from tests.fakes.model import scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001

from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.run import ClaimInvestigation, investigate_claim
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    ClaimedProductProposal,
    ClaimSplit,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS
from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import REQUIRED_EVIDENCE, EvidenceState
from claim_agent.domain.models import Case, Order, Shipment
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentRecord
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentStore

CASE = Case.model_validate(CASE_1001)
SHIPMENT = Shipment.model_validate(SHIPMENT_1001)
ORDER = Order.model_validate(ORDER_1001)
RECORD = CaseRecord(case=CASE, shipment=SHIPMENT, order=ORDER)

COLLAGEN = "Liposomal Tripeptide Collagen"
COLLAGEN_SKU = "COLLAGEN1"
AMPOULE = "Additional Collagen Ampoule Duo"
AMPOULE_SKU = "AMP1"


def a_context() -> ClaimContext:
    return ClaimContext(
        order_value_usd=Decimal("90.00"),
        is_high_value=False,
        days_since_delivery=8,
        delivered_date=CASE.delivered_date,
    )


def a_split(*products: tuple[str, str]) -> ClaimSplit:
    return ClaimSplit(
        claimed_products=tuple(
            ClaimedProductProposal(
                name=name,
                sku=sku,
                quantity=1,
                damage_attachment_ids=("ATT-CASE-1001-02",),
                reasoning="The photograph shows this one broken.",
            )
            for name, sku in products
        ),
        reasoning="The description and the photographs agree on which products broke.",
    )


def a_conclusion(*products: tuple[str, str]) -> InvestigationConclusion:
    return InvestigationConclusion(
        evidence=tuple(
            EvidenceJudgement(
                kind=kind,
                state=EvidenceState.PRESENT,
                observed="Clearly visible in the photograph.",
                attachment_id="ATT-CASE-1001-02",
            )
            for kind in REQUIRED_EVIDENCE
        ),
        assessments=tuple(
            AssessmentJudgement(
                name=name,
                passed=True,
                reasoning="Plain from the photographs.",
            )
            for name in REQUIRED_ASSESSMENTS
        ),
        damaged_items=tuple(
            DamagedItem(product_name=name, quantity=1, sku=sku) for name, sku in products
        ),
        recommendation=Recommendation.APPROVE,
        reasoning="The photographs show it broken and it is on the invoice.",
        email_subject="About your damaged order",
        email_body="We are sorry. We approved your damage claim.",
    )


async def run_claim(
    *,
    split: ClaimSplit,
    conclusion: InvestigationConclusion | None,
    policy: Policy | None = None,
    events: EventStream | None = None,
    precedent_store: PrecedentStore | None = None,
) -> ClaimInvestigation:
    answers = (split,) if conclusion is None else (split, conclusion)
    async with httpx.AsyncClient(base_url="http://shipbob.test") as http:
        with respx.mock(assert_all_called=False) as shipbob:
            shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
            shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
            return await investigate_claim(
                record=RECORD,
                context=a_context(),
                evidence=EvidenceClient(http),
                fetcher=ImageFetcher(http, Settings(attachment_cache_dir=None)),
                chat=scripted(
                    *[AIMessage(content="I have what I need.") for _ in range(len(answers))]
                ),
                structured=StructuredModel(scripted(*answers), max_attempts=1),
                events=events if events is not None else EventStream(),
                policy=policy if policy is not None else Policy(),
                precedent_store=precedent_store,
            )


async def test_fr_1_3_the_split_and_the_investigation_each_get_their_own_budget() -> None:
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
    )

    allowed = Policy().max_agent_steps
    assert claim.triage.budget.steps_allowed == allowed
    assert claim.findings is not None
    assert claim.findings.budget.steps_allowed == allowed
    assert claim.findings.budget.steps_used < allowed


async def test_fr_1b_1_a_claim_of_two_products_is_one_run_answering_for_both() -> None:
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
    )

    assert claim.findings is not None
    assert sorted(line.product_name for line in claim.findings.lines) == sorted([AMPOULE, COLLAGEN])
    assert claim.findings.conclusion is not None
    assert claim.findings.conclusion.recommendation is Recommendation.APPROVE


async def test_fr_1_20_the_cap_holds_the_one_figure_a_claim_recommends() -> None:
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)).model_copy(
            update={"recommended_amount_usd": "150.00"}
        ),
        policy=Policy(reimbursement_cap_usd=Decimal("100.00")),
    )

    assert claim.findings is not None
    assert claim.findings.amount.proposed_usd == Decimal("150.00")
    assert claim.findings.amount.amount_usd == Decimal("100.00")
    assert claim.findings.amount.cap_applied is True


async def test_fr_1a_4_an_unsettled_split_investigates_nothing() -> None:
    claim = await run_claim(
        split=ClaimSplit(
            is_ambiguous=True,
            ambiguity="The photograph shows a 24oz bottle and the order holds two of them.",
            reasoning="The images do not tell the two apart.",
        ),
        conclusion=None,
    )

    assert claim.findings is None
    assert claim.triage.is_ambiguous
    assert "24oz" in (claim.triage.ambiguity or "")


async def test_nfr_8_one_claim_looks_at_its_evidence_once_however_many_products() -> None:
    with respx.mock(assert_all_called=False) as shipbob:
        listing = shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
        invoicing = shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
        async with httpx.AsyncClient(base_url="http://shipbob.test") as http:
            from claim_agent.agent.observations import ObservationCache

            cache = ObservationCache()
            await investigate_claim(
                record=RECORD,
                context=a_context(),
                evidence=EvidenceClient(http),
                fetcher=ImageFetcher(http, Settings(attachment_cache_dir=None)),
                chat=scripted(*[AIMessage(content="Done.") for _ in range(2)]),
                structured=StructuredModel(
                    scripted(
                        a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
                        a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
                    ),
                    max_attempts=1,
                ),
                events=EventStream(),
                policy=Policy(),
                cache=cache,
            )

    assert invoicing.call_count == 1
    assert listing.call_count == 1


async def test_nfr_1_the_same_claim_investigated_twice_comes_out_the_same() -> None:
    async def once() -> ClaimInvestigation:
        return await run_claim(
            split=a_split((COLLAGEN, COLLAGEN_SKU)),
            conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU)),
        )

    first, second = await once(), await once()

    assert first.findings is not None
    assert second.findings is not None
    assert first.findings.outcome == second.findings.outcome
    assert first.findings.amount == second.findings.amount
    assert first.findings.drafted_email == second.findings.drafted_email


async def test_nfr_4_a_claim_whose_invoice_cannot_be_had_still_reaches_a_person() -> None:
    async with httpx.AsyncClient(base_url="http://shipbob.test") as http:
        with respx.mock(assert_all_called=False) as shipbob:
            shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
            shipbob.post("/invoices/generate").respond(422, json={"error": "invoice_unavailable"})
            claim = await investigate_claim(
                record=RECORD,
                context=a_context(),
                evidence=EvidenceClient(http),
                fetcher=ImageFetcher(http, Settings(attachment_cache_dir=None)),
                chat=scripted(*[AIMessage(content="Done.") for _ in range(2)]),
                structured=StructuredModel(
                    scripted(
                        a_split((COLLAGEN, COLLAGEN_SKU)), a_conclusion((COLLAGEN, COLLAGEN_SKU))
                    ),
                    max_attempts=1,
                ),
                events=EventStream(),
                policy=Policy(),
            )

    assert claim.findings is not None
    assert claim.findings.outcome.recommendation is not Recommendation.APPROVE
    assert not claim.findings.amount.is_payable


async def test_the_whole_claim_narrates_itself_on_one_stream() -> None:
    events = EventStream()
    await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        events=events,
    )

    said = events.events()
    assert said, "an investigation that says nothing leaves a screen blank"
    assert [event.sequence for event in said] == list(range(1, len(said) + 1))
    kinds = [event.kind for event in said]
    assert kinds.index(EventKind.CLAIM_SPLIT) < kinds.index(EventKind.INVESTIGATION_STARTED)

    assert kinds.count(EventKind.INVESTIGATION_STARTED) == 1
    assert kinds.count(EventKind.INVESTIGATION_FINISHED) == 1


def a_closed_claim(precedent_id: str, product: str, sku: str) -> PrecedentRecord:
    return PrecedentRecord(
        precedent_id=precedent_id,
        case_id=f"CASE-9{precedent_id[-3:]}",
        claim_line_id=f"{precedent_id}-L01",
        user_id="283959",
        product_name=product,
        sku=sku,
        unit_price=Decimal("52.00"),
        merchant_account=(
            "Customer received order and product arrived damaged. Both product and "
            "shipping box damaged. Damage due to poor packaging."
        ),
        match=MatchOutcome.MATCHED,
        evidence=(),
        assessments=(),
        outcome=Recommendation.REQUEST_REP_CLARIFICATION,
        amount_usd=None,
        cap_applied=False,
        rep_note="Refused: the crushing happened after delivery.",
        withdrawn=False,
        closed_at=datetime(2026, 1, 8, tzinfo=UTC),
    )


async def test_fr_s_5_the_claim_is_looked_up_in_the_store_before_it_is_investigated(
    tmp_path: Path,
) -> None:
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(a_closed_claim("PREC-901", COLLAGEN, COLLAGEN_SKU))
    store.record(a_closed_claim("PREC-902", AMPOULE, AMPOULE_SKU))
    events = EventStream()

    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        precedent_store=store,
        events=events,
    )

    assert claim.findings is not None
    kinds = [event.kind for event in events.events()]
    assert kinds.index(EventKind.PRECEDENT_GATHERED) < kinds.index(EventKind.INVESTIGATION_STARTED)


async def test_fr_s_13_a_claim_run_without_a_store_is_investigated_all_the_same(
    tmp_path: Path,
) -> None:
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU)),
        precedent_store=None,
    )

    assert claim.findings is not None


async def test_fr_s_13_a_store_that_cannot_be_read_never_stops_a_claim(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "claims.db"
    broken.write_text("this is not a database at all")

    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU)),
        precedent_store=PrecedentStore(broken),
    )

    assert claim.findings is not None
