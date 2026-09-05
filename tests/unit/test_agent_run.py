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
    """The facts the deterministic screen worked out before any of this ran (FR-0.5)."""
    return ClaimContext(
        order_value_usd=Decimal("90.00"),
        is_high_value=False,
        days_since_delivery=8,
        delivered_date=CASE.delivered_date,
    )


def a_split(*products: tuple[str, str]) -> ClaimSplit:
    """A settled split naming each of these products as damaged."""
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
    """A well-evidenced conclusion recommending payment for these products.

    One conclusion covers the whole claim, however many products are on it (FR-1b.1).
    Its email writes no amount of its own; code adds the capped figure after the model
    has answered (FR-1.21).
    """
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
    """Investigate one claim against a scripted model.

    The chat model is scripted to conclude at once every time it is asked, so no tools
    are called and the test is about what happens around the run rather than inside it.
    `conclusion` is what the one investigation pass is handed after the split, and is
    `None` for a claim that never reaches it.
    """
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
                # One "I am finished" reply per pass: the split, then the investigation.
                chat=scripted(
                    *[AIMessage(content="I have what I need.") for _ in range(len(answers))]
                ),
                structured=StructuredModel(scripted(*answers), max_attempts=1),
                events=events if events is not None else EventStream(),
                policy=policy if policy is not None else Policy(),
                precedent_store=precedent_store,
            )


async def test_fr_1_3_the_split_and_the_investigation_each_get_their_own_budget() -> None:
    """FR-1.3: two allowances on a claim, not one shared between the passes.

    The investigation starts from a full allowance rather than from what working out
    the split happened to leave.
    """
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
    """FR-1b.1, FR-1b.3: one investigation, one next action, one email, two products.

    This is the change the merged run was made for. Two damaged products used to be two
    runs and two emails to one merchant about one parcel; now there is one set of
    findings naming both, with a single recommendation on it.

    What that recommendation *is* is not asserted here. The scripted run never looks at
    an image, so the claim's shared evidence comes back missing and the rules withhold
    the payment — which is right, and is covered where the rules are, in
    `test_agent_investigate`.
    """
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
    )

    assert claim.findings is not None
    assert sorted(line.product_name for line in claim.findings.lines) == sorted([AMPOULE, COLLAGEN])
    assert claim.findings.conclusion is not None
    assert claim.findings.conclusion.recommendation is Recommendation.APPROVE


async def test_fr_1_20_the_cap_holds_the_one_figure_a_claim_recommends() -> None:
    """FR-1.20: three products at fifty each are a claim of one hundred and fifty, capped.

    The old shape added separate figures up afterwards and then withdrew approvals it had
    already granted. One run proposes one figure, so the cap simply holds it — which is
    what settles whether the cap is per product or per claim.
    """
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
    """FR-1a.4: no product may be investigated while it is unclear which are claimed.

    A wrong split is silent and expensive, so the claim states what is unclear and no
    per-product run happens at all.
    """
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
    """NFR-8: an image is looked at once per claim, not once per damaged product.

    The costly work is reading photographs, so two products in one claim share what was
    already seen rather than each paying for it again.
    """
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

    # One priced invoice for the whole claim, however many products were investigated.
    assert invoicing.call_count == 1
    assert listing.call_count == 1


async def test_nfr_1_the_same_claim_investigated_twice_comes_out_the_same() -> None:
    """NFR-1: two identical claims have to arrive at a representative looking identical.

    Proves everything around the model is repeatable. It says nothing about the model
    itself, which is scripted here — that gap is recorded in DESIGN.md rather than
    papered over.
    """

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
    """NFR-4, FR-1.18: a shipment ShipBob will not price is not priced from somewhere else.

    The claim is investigated and handed over with that as the stated reason. Falling
    back to the order's prices would put a figure in front of a representative that did
    not come from where the report says it came from.
    """
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
    """NFR-3: somebody watching sees the split, then the investigation, in order.

    One stream and one numbering, so a screen can lay the messages out in the order
    they happened rather than guessing at it.
    """
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
    # One investigation, so it starts once and finishes once however many products.
    assert kinds.count(EventKind.INVESTIGATION_STARTED) == 1
    assert kinds.count(EventKind.INVESTIGATION_FINISHED) == 1


# --- The claim is given the claims like it, before it is investigated -------


def a_closed_claim(precedent_id: str, product: str, sku: str) -> PrecedentRecord:
    """One past claim a representative already decided, about the named product."""
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
    """FR-S.5, FR-S.6: one search per product, one set, and it happens before the run.

    Precedent arrives with the claim rather than being something the run may decide to
    look up, and the products on the claim are what it is searched on.
    """
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
    """FR-S.13, NFR-4: no store is an ordinary state, never a reason to fail a claim."""
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU)),
        precedent_store=None,
    )

    assert claim.findings is not None


async def test_fr_s_13_a_store_that_cannot_be_read_never_stops_a_claim(
    tmp_path: Path,
) -> None:
    """FR-S.13, NFR-4: precedent failing is not the claim failing.

    The investigation is the expensive part and it has already been paid for by the time
    the store is read. Losing it because a file on disk was unreadable would be the worst
    possible trade.
    """
    broken = tmp_path / "claims.db"
    broken.write_text("this is not a database at all")

    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU)),
        conclusion=a_conclusion((COLLAGEN, COLLAGEN_SKU)),
        precedent_store=PrecedentStore(broken),
    )

    assert claim.findings is not None
