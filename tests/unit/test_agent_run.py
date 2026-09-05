"""Investigating a whole claim: the split, then every product, then the total.

Two things are checked here that no single product's investigation can check for
itself. Each product gets its own step allowance, so a complicated one cannot starve
a simple one (FR-1b.3). And the reimbursement cap is applied across the claim as
well as within each product, because three products at fifty dollars each are each
fine and together are not — the hole FR-1.20 warns about, where a cap is got round by
splitting a claim into more products.

Everything is driven by a scripted model. Nothing reaches Anthropic and nothing needs
a key, so the same script always produces the same claim (NFR-1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import respx
from langchain_core.messages import AIMessage
from tests.fakes.model import scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001

from claim_agent.agent.budget import BudgetSnapshot
from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import LineInvestigation
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.run import ClaimInvestigation, apply_claim_cap, investigate_claim
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    ClaimedProductProposal,
    ClaimSplit,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS
from claim_agent.domain.claim_line import ClaimedProduct, MatchOutcome, build_claim_lines
from claim_agent.domain.evidence import REQUIRED_EVIDENCE, EvidenceState
from claim_agent.domain.models import Case, DraftedEmail, Order, Shipment
from claim_agent.domain.outcome import OutcomeDecision, OverrideReason, Recommendation
from claim_agent.domain.precedent import PrecedentRecord
from claim_agent.domain.reimbursement import AmountComponent, AmountDerivation
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


def a_conclusion(product: str, sku: str) -> InvestigationConclusion:
    """A well-evidenced conclusion recommending payment for one product.

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
        damaged_items=(DamagedItem(product_name=product, quantity=1, sku=sku),),
        recommendation=Recommendation.APPROVE,
        reasoning="The photographs show it broken and it is on the invoice.",
        email_subject="About your damaged order",
        email_body="We are sorry. We approved your damage claim.",
    )


def in_claim_line_order(products: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Put products in the order `build_claim_lines` will hand them back.

    Claim lines are sorted by product code so that the same claim always produces the
    same identifiers. A test that scripts one conclusion per product has to script them
    in that order, or a conclusion about one product lands on another — which reads as
    a product that cannot be priced, and looks like a bug in the code under test rather
    than in the script.
    """
    return sorted(products, key=lambda product: (product[1] or "", product[0]))


async def run_claim(
    *,
    split: ClaimSplit,
    conclusions: Sequence[InvestigationConclusion],
    policy: Policy | None = None,
    events: EventStream | None = None,
    precedent_store: PrecedentStore | None = None,
) -> ClaimInvestigation:
    """Investigate one claim against a scripted model.

    The chat model is scripted to conclude at once every time it is asked, so no
    tools are called and the test is about what happens around the runs rather than
    inside them. `conclusions` is what the split pass and then each product's pass
    are handed, in that order — see `in_claim_line_order`.
    """
    async with httpx.AsyncClient(base_url="http://shipbob.test") as http:
        with respx.mock(assert_all_called=False) as shipbob:
            shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
            shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
            return await investigate_claim(
                record=RECORD,
                context=a_context(),
                evidence=EvidenceClient(http),
                fetcher=ImageFetcher(http, Settings(attachment_cache_dir=None)),
                # One "I am finished" reply per pass: the split, then each product.
                chat=scripted(
                    *[AIMessage(content="I have what I need.") for _ in range(len(conclusions) + 1)]
                ),
                structured=StructuredModel(scripted(split, *conclusions), max_attempts=1),
                events=events if events is not None else EventStream(),
                policy=policy if policy is not None else Policy(),
                precedent_store=precedent_store,
            )


async def test_fr_1_3_a_claim_with_two_products_has_a_budget_for_each() -> None:
    """FR-1.3: budgets are per run, so a difficult product cannot starve a simple one.

    Three allowances are spent on a two-product claim — one for working out the split
    and one for each product — and none of them is shared.
    """
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusions=[
            a_conclusion(name, sku)
            for name, sku in in_claim_line_order([(COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)])
        ],
    )

    allowed = Policy().max_agent_steps
    assert claim.triage.budget.steps_allowed == allowed
    for line in claim.lines:
        assert line.budget.steps_allowed == allowed
        # Each product started from a full allowance rather than what the split left.
        assert line.budget.steps_used < allowed


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
        conclusions=[],
    )

    assert claim.lines == ()
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
                chat=scripted(*[AIMessage(content="Done.") for _ in range(3)]),
                structured=StructuredModel(
                    scripted(
                        a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
                        *[
                            a_conclusion(name, sku)
                            for name, sku in in_claim_line_order(
                                [(COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)]
                            )
                        ],
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
            conclusions=[a_conclusion(COLLAGEN, COLLAGEN_SKU)],
        )

    first, second = await once(), await once()

    assert first.recommended_total_usd == second.recommended_total_usd
    assert [line.outcome for line in first.lines] == [line.outcome for line in second.lines]
    assert [line.amount for line in first.lines] == [line.amount for line in second.lines]
    assert [line.drafted_email for line in first.lines] == [
        line.drafted_email for line in second.lines
    ]


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
                        a_split((COLLAGEN, COLLAGEN_SKU)), a_conclusion(COLLAGEN, COLLAGEN_SKU)
                    ),
                    max_attempts=1,
                ),
                events=EventStream(),
                policy=Policy(),
            )

    assert len(claim.lines) == 1
    line = claim.lines[0]
    assert line.outcome.recommendation is not Recommendation.APPROVE
    assert not line.amount.is_payable


async def test_the_whole_claim_narrates_itself_on_one_stream() -> None:
    """The screen watches several products at once, so every message names its own.

    A claim-level message carries no product; a product's message always carries one,
    or a representative could not tell which of two investigations a line belonged to.
    """
    events = EventStream()
    await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusions=[
            a_conclusion(name, sku)
            for name, sku in in_claim_line_order([(COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)])
        ],
        events=events,
    )

    said = events.events()
    assert said, "an investigation that says nothing leaves a screen blank"
    assert [event.sequence for event in said] == list(range(1, len(said) + 1))
    named = {event.claim_line_id for event in said if event.claim_line_id is not None}
    assert len(named) == 2


# --- The cap across a whole claim (FR-1.20) ----------------------------------
#
# Tested against `apply_claim_cap` rather than through a whole investigation, because
# that is where the rule lives. Reaching it end to end needs every product approved,
# which needs all four pieces of evidence settled, which needs a scripted run that
# looks at each image — a great deal of scaffolding standing between the test and the
# one line of arithmetic it is actually about.


def a_priced_line(
    product: str, sku: str, paid: str, *, recommendation: Recommendation
) -> LineInvestigation:
    """A finished investigation recommending `recommendation`, refunding `paid`.

    `paid` is the figure being recommended, which is what the claim-level cap adds up.
    The item is written as refunding its whole price, so the numbers here are internally
    consistent without the refund percentage getting between the test and the cap it is
    actually about.
    """
    amount = AmountDerivation(
        components=(
            AmountComponent(
                product_name=product,
                sku=sku,
                quantity=1,
                unit_price=Decimal(paid),
            ),
        ),
        items_total_usd=Decimal(paid),
        proposed_usd=Decimal(paid),
        amount_usd=Decimal(paid),
        cap_usd=Decimal("100.00"),
        cap_applied=False,
        priced_from="INV-342578703",
    )
    line = build_claim_lines(
        "CASE-1001", [ClaimedProduct(name=product, sku=sku, quantity=1)], ORDER
    )[0]
    return LineInvestigation(
        line=line,
        evidence=(),
        assessments=(),
        outcome=OutcomeDecision(
            recommendation=recommendation,
            recommended_by_agent=recommendation,
            explanation="Judged on its own evidence.",
        ),
        amount=amount,
        concerns=(),
        drafted_email=DraftedEmail(
            to="m@example.test", subject="About your order", body=f"We will refund ${paid}."
        ),
        ledger=(),
        budget=BudgetSnapshot(
            steps_used=2,
            steps_allowed=12,
            image_analyses_used=1,
            image_analyses_allowed=20,
            tool_retries_used=0,
            tool_retries_allowed_per_call=2,
            limits_reached=(),
        ),
        conclusion=None,
    )


def test_fr_1_20_two_products_within_the_cap_are_left_alone() -> None:
    """FR-1.20: the cap only bites when the claim actually goes over it."""
    verdict = apply_claim_cap(
        [
            a_priced_line(COLLAGEN, COLLAGEN_SKU, "52.00", recommendation=Recommendation.APPROVE),
            a_priced_line(AMPOULE, AMPOULE_SKU, "38.00", recommendation=Recommendation.APPROVE),
        ],
        policy=Policy(),
    )

    assert verdict.total_usd == Decimal("90.00")
    assert verdict.applied is False
    assert verdict.complaint is None
    for line in verdict.lines:
        assert line.outcome.recommendation is Recommendation.APPROVE


def test_fr_1_20_the_cap_limits_the_whole_claim_and_not_only_each_product() -> None:
    """FR-1.20: otherwise the cap is got round by splitting a claim into more products.

    Two products at $52.00 and $38.00 are each well under the $100 cap. Together they
    come to $90.00, so a cap of $80.00 is breached by the claim without either product
    breaching it alone — which is exactly the hole the requirement warns about.

    Nothing is trimmed and neither product is chosen over the other: both go to a
    representative, who can decide what to pay.
    """
    verdict = apply_claim_cap(
        [
            a_priced_line(COLLAGEN, COLLAGEN_SKU, "52.00", recommendation=Recommendation.APPROVE),
            a_priced_line(AMPOULE, AMPOULE_SKU, "38.00", recommendation=Recommendation.APPROVE),
        ],
        policy=Policy(reimbursement_cap_usd=Decimal("80.00")),
    )

    assert verdict.applied is True
    assert verdict.total_usd == Decimal("90.00")
    assert verdict.complaint is not None
    for line in verdict.lines:
        assert line.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
        assert OverrideReason.CLAIM_CAP_EXCEEDED in line.outcome.overrides
        # What the investigation itself concluded is kept beside the new answer, so a
        # representative can see the product was sound and the claim's total was not.
        assert line.outcome.recommended_by_agent is Recommendation.APPROVE
        # The draft promised a figure that would no longer be paid.
        assert line.drafted_email is None


def test_fr_1_20_the_claim_cap_can_only_withhold_a_payment_never_cause_one() -> None:
    """FR-1.20: the cap is a reason not to pay, and never a reason to pay.

    A product going back to the merchant for a photograph, or already handed to a
    person, is left exactly as it was. The cap must not re-open it and must not turn a
    request for evidence into a payment.
    """
    verdict = apply_claim_cap(
        [
            a_priced_line(COLLAGEN, COLLAGEN_SKU, "52.00", recommendation=Recommendation.APPROVE),
            a_priced_line(AMPOULE, AMPOULE_SKU, "38.00", recommendation=Recommendation.APPROVE),
            a_priced_line(
                "Red/Black HUGE Shaker", "0157", "12.99", recommendation=Recommendation.REQUEST_INFO
            ),
        ],
        policy=Policy(reimbursement_cap_usd=Decimal("80.00")),
    )

    asked = next(
        line
        for line in verdict.lines
        if line.outcome.recommended_by_agent is Recommendation.REQUEST_INFO
    )
    assert asked.outcome.recommendation is Recommendation.REQUEST_INFO
    assert OverrideReason.CLAIM_CAP_EXCEEDED not in asked.outcome.overrides
    assert asked.drafted_email is not None
    # Only what was going to be paid counts towards the total.
    assert verdict.total_usd == Decimal("90.00")


def test_fr_1_20_a_claim_of_one_product_is_capped_the_same_way() -> None:
    """FR-1.20: a single product over the cap is held back like any other claim."""
    verdict = apply_claim_cap(
        [a_priced_line(COLLAGEN, COLLAGEN_SKU, "52.00", recommendation=Recommendation.APPROVE)],
        policy=Policy(reimbursement_cap_usd=Decimal("20.00")),
    )

    assert verdict.applied is True
    assert verdict.lines[0].outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION


def test_the_whole_claim_cap_can_be_turned_off() -> None:
    """FR-1.20, open question 2: whether the cap limits a claim or a product is unsettled.

    Neither reading is stated by ShipBob, so which one applies is a setting rather than
    a decision buried in the code.
    """
    lines = [
        a_priced_line(COLLAGEN, COLLAGEN_SKU, "52.00", recommendation=Recommendation.APPROVE),
        a_priced_line(AMPOULE, AMPOULE_SKU, "38.00", recommendation=Recommendation.APPROVE),
    ]

    verdict = apply_claim_cap(
        lines,
        policy=Policy(reimbursement_cap_usd=Decimal("80.00"), cap_applies_to_whole_claim=False),
    )

    assert verdict.applied is False
    for line in verdict.lines:
        assert line.outcome.recommendation is Recommendation.APPROVE


async def test_fr_1b_3_two_products_reach_their_own_answers() -> None:
    """FR-1b.3: a weak product must not drag down a strong one, or the other way about.

    The two runs are given different conclusions and come back different. Neither
    product's answer is touched by the other's, which is what splitting a claim before
    investigating it buys.
    """
    ordered = in_claim_line_order([(COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)])
    conclusions = [
        a_conclusion(name, sku).model_copy(
            update={
                "recommendation": Recommendation.REQUEST_REP_CLARIFICATION
                if index == 0
                else Recommendation.REQUEST_INFO
            }
        )
        for index, (name, sku) in enumerate(ordered)
    ]

    claim = await run_claim(split=a_split(*ordered), conclusions=conclusions)

    assert len(claim.lines) == 2
    # What each run itself concluded is kept whole on its line, which is where a
    # representative reads it. `recommended_by_agent` is what the rules were asked
    # about, and on a line whose email had to be thrown away those differ.
    reached = {
        line.line.product_name: line.conclusion.recommendation
        for line in claim.lines
        if line.conclusion is not None
    }
    assert reached[ordered[0][0]] is Recommendation.REQUEST_REP_CLARIFICATION
    assert reached[ordered[1][0]] is Recommendation.REQUEST_INFO


# --- Every product is given the claims like it, before it is investigated ---


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


async def test_fr_s_5_every_product_is_looked_up_in_the_store_before_it_is_investigated(
    tmp_path: Path,
) -> None:
    """FR-S.5, FR-S.6: one lookup per product, and it happens before any run starts.

    Each product is its own claim from here on, so each gets its own precedent rather
    than the claim sharing one set between them.
    """
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(a_closed_claim("PREC-901", COLLAGEN, COLLAGEN_SKU))
    store.record(a_closed_claim("PREC-902", AMPOULE, AMPOULE_SKU))
    ordered = in_claim_line_order([(COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)])

    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU), (AMPOULE, AMPOULE_SKU)),
        conclusions=[a_conclusion(name, sku) for name, sku in ordered],
        precedent_store=store,
    )

    assert len(claim.lines) == 2


async def test_fr_s_13_a_claim_run_without_a_store_is_investigated_all_the_same(
    tmp_path: Path,
) -> None:
    """FR-S.13, NFR-4: no store is an ordinary state, never a reason to fail a claim."""
    claim = await run_claim(
        split=a_split((COLLAGEN, COLLAGEN_SKU)),
        conclusions=[a_conclusion(COLLAGEN, COLLAGEN_SKU)],
        precedent_store=None,
    )

    assert len(claim.lines) == 1


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
        conclusions=[a_conclusion(COLLAGEN, COLLAGEN_SKU)],
        precedent_store=PrecedentStore(broken),
    )

    assert len(claim.lines) == 1
