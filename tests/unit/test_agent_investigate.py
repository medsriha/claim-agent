"""Investigating one damaged product: what it decides, what it refuses, and how it fails.

Every model here answers from a script the test wrote beforehand, so nothing reaches a
network or a model provider and no key is needed. That is also what makes these tests
about the investigation rather than about the model: the answers are fixed, so what is
left to observe is what the code does with them.

Two groups of tests are worth finding quickly.

**The four questions that decide a payment** are exercised one at a time — evidence that
is short, an image we could not read, a shaky answer, a run that ran out of steps — and
each of them checks that the recommendation moved *away* from paying and never towards
it.

**The isolation tests (FR-1b.4)** are the ones the layer exists for: the same product
with the same evidence reaches the same answer whether it was claimed alone or beside
five others, and the question the model is asked does not change when the other products
arrive in a different order.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import respx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage
from tests.fakes.model import ScriptedModel, scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001

from claim_agent.agent.budget import BudgetLimit
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import LineInvestigation, investigate_line
from claim_agent.agent.ledger import StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.schemas import (
    AMOUNT_PLACEHOLDER,
    AssessmentJudgement,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.agent.tools import LIST_ATTACHMENTS
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome, build_claim_lines
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
    findings_by_kind,
    gaps_the_merchant_can_fill,
)
from claim_agent.domain.models import (
    Attachment,
    Case,
    Invoice,
    Order,
    OrderLineItem,
    Shipment,
)
from claim_agent.domain.outcome import OverrideReason, Recommendation
from claim_agent.domain.precedent import PrecedentRecord, PrecedentSimilarity
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet, RetrievedPrecedent

SHIPBOB = "http://shipbob.test"

# The claim every test works from is CASE-1001, whose case, order, shipment and invoice
# are ShipBob's own sample records. Its order holds two products: an Additional Collagen
# Ampoule Duo at $38.00 and a Liposomal Tripeptide Collagen at $52.00.
CASE = Case.model_validate(CASE_1001)
SHIPMENT = Shipment.model_validate(SHIPMENT_1001)
ORDER = Order.model_validate(ORDER_1001)
INVOICE = Invoice.model_validate(INVOICE_342578703)

COLLAGEN = "Liposomal Tripeptide Collagen"
COLLAGEN_SKU = "COLLAGEN1"
AMPOULE = "Additional Collagen Ampoule Duo"


def images_on_the_claim() -> tuple[Attachment, ...]:
    """The images CASE-1001 actually carries, as the investigation is handed them."""
    listed = ATTACHMENTS_1001["attachments"]
    assert isinstance(listed, list)
    return tuple(Attachment.model_validate(image) for image in listed)


IMAGES = images_on_the_claim()

RECORD = CaseRecord(case=CASE, shipment=SHIPMENT, order=ORDER)
CONTEXT = ClaimContext(
    order_value_usd=Decimal("90.00"),
    is_high_value=False,
    days_since_delivery=8,
    delivered_date=CASE.delivered_date,
)


# --- Building a claim to investigate ----------------------------------------


def build_settings() -> Settings:
    """Settings for a test process, with no credentials and nowhere to cache downloads."""
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url=SHIPBOB,
        attachment_allowed_hosts=("images.test",),
        attachment_cache_dir=None,
        attachment_timeout_seconds=1.0,
    )


def claim_lines(*claimed: ClaimedProduct, order: Order = ORDER) -> tuple[ClaimLine, ...]:
    """Split a claim into lines the way the triage pass does, matching against the order."""
    return build_claim_lines(CASE.case_id, claimed, order)


def a_claim_for_the_collagen(order: Order = ORDER) -> ClaimLine:
    """One claim line: the $52.00 collagen, matched to exactly one line on the order."""
    line = claim_lines(ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU), order=order)[0]
    assert line.match is MatchOutcome.MATCHED
    return line


def five_other_products() -> tuple[ClaimedProduct, ...]:
    """Five more damaged products, so a line can be investigated beside a crowd of them."""
    return (
        ClaimedProduct(name=AMPOULE, quantity=1, sku="AMP1"),
        ClaimedProduct(name="Beef Trachea Chews", quantity=2),
        ClaimedProduct(name="Salmon Skin Twists", quantity=1),
        ClaimedProduct(name="Duck Neck Crunchies", quantity=3),
        ClaimedProduct(name="Turkey Tendon Sticks", quantity=1),
    )


def the_collagen_beside(
    others: Sequence[ClaimedProduct],
) -> tuple[ClaimLine, tuple[ClaimLine, ...]]:
    """Split a claim covering the collagen and some other products, and pick the collagen out.

    Returns the collagen's own claim line and the rest of them, which is exactly what one
    run is given: the product it answers for, and the others as context (FR-1b.2).
    """
    lines = claim_lines(ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU), *others)
    mine = next(line for line in lines if line.product_name == COLLAGEN)
    return mine, tuple(line for line in lines if line is not mine)


# --- Writing the answers the model gives ------------------------------------


def evidence_all_in_hand(**states: EvidenceState) -> tuple[EvidenceJudgement, ...]:
    """The model's read on all four pieces of evidence, present unless a test says otherwise.

    A keyword names one of the four and the state to put it in:
    `evidence_all_in_hand(outer_packaging_photo=EvidenceState.MISSING)`.
    """
    return tuple(
        EvidenceJudgement(
            kind=kind,
            state=states.get(kind.value, EvidenceState.PRESENT),
            observed=f"What the {kind.value.replace('_', ' ')} shows.",
            attachment_id=IMAGES[0].attachment_id,
        )
        for kind in REQUIRED_EVIDENCE
    )


def all_four_answered(confidence: float = 0.9, **passed: bool) -> tuple[AssessmentJudgement, ...]:
    """The four questions, answered yes at a good confidence unless a test says otherwise."""
    return tuple(
        AssessmentJudgement(
            name=name,
            passed=passed.get(name.value, True),
            reasoning=f"Why {name.value.replace('_', ' ')} is answered that way.",
            confidence=confidence,
            attachment_ids=(IMAGES[0].attachment_id,),
        )
        for name in REQUIRED_ASSESSMENTS
    )


def a_conclusion(**overrides: object) -> InvestigationConclusion:
    """A well-evidenced conclusion recommending payment for one collagen.

    It names an amount, because the investigation decides what the damage is worth
    (FR-1.21). $40.00 against a $52.00 item, deliberately: the figure is a judgement about
    the damage rather than a share of the price, so a test that assumed one could be
    derived from the other would be asserting a rule that no longer exists.

    Its email writes no amount of its own. Code adds the figure that got past the cap after
    the model has answered.
    """
    fields: dict[str, object] = {
        "evidence": evidence_all_in_hand(),
        "assessments": all_four_answered(),
        "damaged_items": (DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
        "recommended_amount_usd": "40.00",
        "amount_reasoning": "The bottle is cracked through and the contents are lost.",
        "recommendation": Recommendation.APPROVE,
        "reasoning": "The photographs show the collagen bottle crushed, and it is on the invoice.",
        "concerns": ("The photograph is taken close in, so the outer box is not visible in it.",),
        "confidence": 0.9,
        "email_subject": "About your damaged shipment",
        "email_body": "We have looked at your claim and approved the damaged collagen.",
    }
    fields.update(overrides)
    return InvestigationConclusion.model_validate(fields)


def an_email_with_no_figure(**overrides: object) -> dict[str, object]:
    """Email wording that mentions no amount at all, for a conclusion nobody will pay out.

    Non-approval wording names no figure, which lets a test change one thing at a time.
    """
    fields: dict[str, object] = {
        "email_subject": "About your damaged shipment",
        "email_body": "We have looked at your claim and will be in touch about it.",
    }
    fields.update(overrides)
    return fields


# --- Running one investigation ----------------------------------------------


async def investigate(
    model: ScriptedModel,
    *,
    line: ClaimLine | None = None,
    siblings: Sequence[ClaimLine] = (),
    shared_evidence: Sequence[EvidenceFinding] = (),
    invoice: Invoice | None = INVOICE,
    order: Order = ORDER,
    policy: Policy | None = None,
    events: EventStream | None = None,
    precedent: PrecedentSet | None = None,
) -> LineInvestigation:
    """Investigate one claim line, with everything a test does not care about defaulted.

    The HTTP clients are real ones aimed at a name that only a stand-in answers to, so a
    request that escaped a test would fail loudly rather than reach a machine. Most tests
    here never make one: their model never asks for a tool.
    """
    settings = build_settings()
    async with (
        httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as shipbob_http,
        httpx.AsyncClient() as images_http,
    ):
        return await investigate_line(
            line=line if line is not None else a_claim_for_the_collagen(order),
            record=CaseRecord(case=CASE, shipment=SHIPMENT, order=order),
            context=CONTEXT,
            attachments=IMAGES,
            invoice=invoice,
            evidence=EvidenceClient(shipbob_http, max_attempts=1),
            fetcher=ImageFetcher(images_http, settings),
            chat=model,
            structured=StructuredModel(model, max_attempts=1),
            cache=ObservationCache(),
            events=events if events is not None else EventStream(),
            policy=policy if policy is not None else Policy(),
            shared_evidence=shared_evidence,
            siblings=siblings,
            precedent=precedent,
        )


def a_run_that_concludes(conclusion: InvestigationConclusion) -> ScriptedModel:
    """A model that looks at nothing, says it has seen enough, and fills the form in."""
    return scripted("I have seen enough to answer.", conclusion)


def settled(kind: EvidenceKind, state: EvidenceState) -> EvidenceFinding:
    """One piece of shared evidence, settled once for the whole claim (FR-1a.3)."""
    return EvidenceFinding(
        kind=kind,
        state=state,
        observed=f"What the claim settled about the {kind.value.replace('_', ' ')}.",
        attachment_id=IMAGES[0].attachment_id if state is not EvidenceState.MISSING else None,
        problem="It could not be read." if state is EvidenceState.UNREADABLE else None,
    )


def state_of(result: LineInvestigation, kind: EvidenceKind) -> EvidenceState:
    """What the finished investigation says about one of the four pieces of evidence."""
    return findings_by_kind(result.evidence)[kind].state


# --- A well-evidenced product (FR-1.14, FR-1.18, FR-1.21) -------------------


async def test_a_well_evidenced_product_is_recommended_for_payment_at_the_policy_share() -> None:
    """FR-1.14, FR-1.18: a claim with everything in hand is proposed for payment, priced.

    The figure is the investigation's own judgement of what the damage is worth — $40.00
    against a $52.00 item, deliberately not a share of the price. What the item cost is
    shown beside it as context, and the email carries the figure that got past the cap.
    """
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.outcome.recommendation is Recommendation.APPROVE
    assert result.outcome.recommended_by_agent is Recommendation.APPROVE
    assert result.outcome.was_overridden is False
    assert result.amount.proposed_usd == Decimal("40.00")
    assert result.amount.amount_usd == Decimal("40.00")
    assert result.amount.cap_applied is False
    assert result.amount.items_total_usd == Decimal("52.00")
    assert result.amount.priced_from == "INV-342578703"
    assert result.amount.cap_applied is False
    assert result.drafted_email is not None
    assert result.drafted_email.to == "sakukreja@shipbob.com"
    assert result.drafted_email.is_draft is True
    assert "$40.00" in result.drafted_email.body
    assert AMOUNT_PLACEHOLDER not in result.drafted_email.body


async def test_a_recommendation_is_never_presented_as_settled() -> None:
    """FR-1.17: the email is a draft, and nothing in its own words says so.

    That it is unsent is recorded beside the wording rather than inside it, so no such
    marker can ever reach a merchant.
    """
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.drafted_email is not None
    assert result.drafted_email.is_draft is True
    assert "draft" not in result.drafted_email.body.lower()
    assert "draft" not in result.drafted_email.subject.lower()


async def test_all_four_pieces_of_evidence_and_all_four_questions_are_reported() -> None:
    """FR-2.2, FR-2.3: a representative sees what was found, not what was left out.

    All four pieces of evidence come back in the fixed reporting order whatever
    happened, so nothing has to be inferred from silence.
    """
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert tuple(finding.kind for finding in result.evidence) == REQUIRED_EVIDENCE
    assert tuple(answer.name for answer in result.assessments) == REQUIRED_ASSESSMENTS


# --- Evidence that is short, or that we could not read (FR-1.6, NFR-4) ------


async def test_a_missing_piece_of_evidence_sends_the_claim_back_to_the_merchant() -> None:
    """FR-1.6: nothing is approved partially — what is missing is asked for and the claim waits.

    The investigation recommended paying anyway, which is exactly the case the rule
    exists for: it is applied to the answer afterwards rather than being an instruction
    the model was asked to follow.
    """
    conclusion = a_conclusion(
        evidence=evidence_all_in_hand(outer_packaging_photo=EvidenceState.MISSING),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.outcome.recommended_by_agent is Recommendation.APPROVE
    assert OverrideReason.EVIDENCE_INCOMPLETE in result.outcome.overrides
    assert gaps_the_merchant_can_fill(result.evidence) == (EvidenceKind.OUTER_PACKAGING_PHOTO,)
    assert result.drafted_email is not None


async def test_a_specific_identification_detail_can_be_requested_from_the_merchant() -> None:
    """The request-info path supports actionable gaps beyond the four evidence items."""
    detail = "a clear photograph showing the full product label and SKU"
    conclusion = a_conclusion(
        recommendation=Recommendation.REQUEST_INFO,
        requested_details=(detail,),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.drafted_email is not None
    assert detail in result.drafted_email.body


async def test_an_image_we_could_not_read_goes_to_a_person_and_not_to_the_merchant() -> None:
    """NFR-4, FR-1.7: our own failure is never turned into a request the merchant cannot act on.

    The claim settled that the invoice image could not be read by us. Asking the merchant
    to send it again would be asking them to fix our download, so the line goes to a
    person instead.
    """
    conclusion = a_conclusion(**an_email_with_no_figure())

    result = await investigate(
        a_run_that_concludes(conclusion),
        shared_evidence=(settled(EvidenceKind.INVOICE, EvidenceState.UNREADABLE),),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.EVIDENCE_UNREADABLE in result.outcome.overrides
    assert state_of(result, EvidenceKind.INVOICE) is EvidenceState.UNREADABLE
    assert EvidenceKind.INVOICE not in gaps_the_merchant_can_fill(result.evidence)


async def test_a_question_answered_no_is_not_the_same_as_one_never_answered() -> None:
    """FR-1.12: a failed judgement asks the representative to clarify what is wrong.

    A question nobody answered is the other thing entirely — an unfinished investigation
    — so an answer of no is kept as an answer rather than being dropped.
    """
    conclusion = a_conclusion(
        assessments=all_four_answered(damage_visible=False),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.ASSESSMENT_FAILED in result.outcome.overrides
    assert result.drafted_email is None
    answered = {answer.name: answer.passed for answer in result.assessments}
    assert answered[AssessmentName.DAMAGE_VISIBLE] is False
    assert len(result.assessments) == 4


async def test_a_question_the_run_never_answered_is_not_written_down_as_an_answer() -> None:
    """FR-2.3, NFR-4: an unfinished investigation must never read as a clean one.

    The run answered three of the four questions. The fourth is absent from the write-up
    rather than being recorded as a no, because those two lead different places — one
    back to the merchant, the other to a person.
    """
    conclusion = a_conclusion(
        assessments=all_four_answered()[:3],
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert tuple(answer.name for answer in result.assessments) == REQUIRED_ASSESSMENTS[:3]
    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.INVESTIGATION_INCOMPLETE in result.outcome.overrides


# --- Uncertainty and exhaustion (FR-1.15, FR-1.16) --------------------------


async def test_a_shaky_investigation_is_never_allowed_to_recommend_paying() -> None:
    """FR-1.15: where confidence is low the line goes to a person, with the doubt stated.

    The threshold is the one in the claim policy, so a test sets it rather than assuming
    the number written into it.
    """
    conclusion = a_conclusion(
        confidence=0.4,
        **an_email_with_no_figure(),
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        policy=Policy(min_assessment_confidence=0.7),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.NOT_CONFIDENT_ENOUGH in result.outcome.overrides
    assert "0.40" in result.outcome.explanation


async def test_a_run_that_used_up_its_steps_asks_the_rep_with_findings_intact() -> None:
    """FR-1.16: a representative is handed the work, not an empty result.

    The run is given one step, spends it asking for the images, and has nothing left. The
    evidence the claim had already settled is still in the write-up, and so is the record
    of the one thing the run managed to do.
    """
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {"name": LIST_ATTACHMENTS, "args": {}, "id": "call-1", "type": "tool_call"}
            ],
        )
    )

    with respx.mock(assert_all_called=False) as api:
        api.get(f"{SHIPBOB}/cases/{CASE.case_id}/attachments").respond(200, json=ATTACHMENTS_1001)
        result = await investigate(
            model,
            policy=Policy(max_agent_steps=1),
            shared_evidence=(settled(EvidenceKind.CUSTOMER_CONFIRMATION, EvidenceState.PRESENT),),
        )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.BUDGET_EXHAUSTED in result.outcome.overrides
    assert result.conclusion is None
    assert result.confidence is None
    assert result.drafted_email is None
    assert BudgetLimit.STEPS in result.budget.limits_reached
    assert [entry.name for entry in result.ledger if entry.kind is StepKind.TOOL_CALL] == [
        LIST_ATTACHMENTS
    ]
    assert state_of(result, EvidenceKind.CUSTOMER_CONFIRMATION) is EvidenceState.PRESENT
    assert result.concerns != ()


async def test_a_model_that_cannot_be_reached_produces_a_write_up_rather_than_an_error() -> None:
    """NFR-4: no failure path leads to an unreviewed approval or a dropped claim.

    The provider fails on the very first turn, so nothing at all was established. The
    line still comes back as a finished write-up recommending that a person look at it,
    with the reason among its concerns and every piece of evidence shown as one we do not
    have.
    """
    result = await investigate(scripted(ModelConnectionError("the socket closed")))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.conclusion is None
    assert result.drafted_email is None
    assert BudgetLimit.STEPS not in result.budget.limits_reached
    assert OverrideReason.BUDGET_EXHAUSTED not in result.outcome.overrides
    assert len(result.evidence) == 4
    assert all(finding.state is EvidenceState.MISSING for finding in result.evidence)
    assert result.concerns != ()


# --- Which product, and what it is worth (FR-1.13, FR-1.19, FR-1.20, FR-1.21)


def an_order_with_two_lines_of_one_name() -> Order:
    """An order carrying the same product name twice at two different prices.

    Constructed rather than taken from ShipBob's samples: none of the five sample orders
    lists one name twice, and this is the situation the requirements single out as the
    one the system must refuse to guess at (FR-1.13).
    """
    return Order(
        order_id="334291211",
        user_id="334430",
        line_items=(
            OrderLineItem(
                name="CleanBoss Multi Surface Cleaner 24oz",
                sku="A00300",
                quantity=1,
                unit_price=Decimal("12.99"),
            ),
            OrderLineItem(
                name="CleanBoss Multi Surface Cleaner 24oz",
                sku="A00301",
                quantity=1,
                unit_price=Decimal("24.99"),
            ),
        ),
    )


async def test_a_product_that_could_be_either_of_two_order_lines_is_never_priced() -> None:
    """FR-1.13: the system asks which product was damaged rather than picking the likelier.

    The two candidates cost different amounts, so choosing one would invent the payout.
    Nothing is priced, and what is unclear is put in front of the representative.
    """
    order = an_order_with_two_lines_of_one_name()
    line = claim_lines(
        ClaimedProduct(name="CleanBoss Multi Surface Cleaner 24oz", quantity=1), order=order
    )[0]
    assert line.match is MatchOutcome.AMBIGUOUS

    conclusion = a_conclusion(
        damaged_items=(
            DamagedItem(product_name="CleanBoss Multi Surface Cleaner 24oz", quantity=1),
        ),
        is_ambiguous=True,
        ambiguity="The photograph shows a 24oz bottle, and the order holds two of them.",
        recommendation=Recommendation.REQUEST_INFO,
        **an_email_with_no_figure(),
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        line=line,
        order=order,
        invoice=Invoice(invoice_id="INV-342578703", line_items=order.line_items),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.drafted_email is None
    # The figure the investigation named is still shown; the rules withhold the payment,
    # which is what stops it being made. Zeroing it would hide what was proposed.
    assert result.amount.components == ()
    assert result.amount.components == ()
    assert any("two of them" in concern for concern in result.concerns)


async def test_an_ambiguous_product_is_judged_against_the_order_and_not_against_the_claim() -> None:
    """FR-1.13, FR-1b.4: which products are on the order is the same however a claim is split.

    The investigation recommended paying. It cannot be paid, because the damaged product
    matches two lines on the order that carry different prices — a fact about the order,
    which does not change when the same claim is divided differently.
    """
    order = an_order_with_two_lines_of_one_name()
    line = claim_lines(
        ClaimedProduct(name="CleanBoss Multi Surface Cleaner 24oz", quantity=1), order=order
    )[0]

    result = await investigate(
        a_run_that_concludes(a_conclusion(**an_email_with_no_figure())),
        line=line,
        order=order,
        invoice=Invoice(invoice_id="INV-342578703", line_items=order.line_items),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides
    assert "more than one line on the order" in result.outcome.explanation


async def test_a_product_that_is_not_on_the_order_cannot_be_paid_for() -> None:
    """FR-1.10, FR-1a.2: a claim for something that was never ordered is a finding, not an error.

    The line is still investigated and still reported on. It simply cannot be priced, so
    it goes to a person with the reason said plainly.
    """
    line = claim_lines(ClaimedProduct(name="Beef Trachea Chews", quantity=1))[0]
    assert line.match is MatchOutcome.NOT_ON_ORDER

    conclusion = a_conclusion(
        damaged_items=(DamagedItem(product_name="Beef Trachea Chews", quantity=1),),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion), line=line)

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides
    assert "not on the order" in result.outcome.explanation
    # The figure the investigation named is still shown, and nothing is paid on it. Zeroing
    # it would hide what was proposed; the rules withholding it is what stops the payment.
    assert result.amount.components == ()
    assert result.amount.proposed_usd == Decimal("40.00")


async def test_only_the_damaged_items_are_covered_and_never_the_whole_order() -> None:
    """FR-1.19: one crushed bottle in a two-product order reimburses one bottle.

    The order comes to $90.00 and holds two products. The claim is for one of them, so
    only that one is priced for context — a recommendation is never worked out from the
    whole order.
    """
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.amount.items_total_usd == Decimal("52.00")
    assert [component.product_name for component in result.amount.components] == [COLLAGEN]


async def test_the_amount_is_capped() -> None:
    """FR-1.20: a claim worth more than the cap is recommended at the cap, and says so.

    Easy to construct now that the investigation names the figure: it proposes $180.00 for
    four badly damaged tubs, and the cap brings that back to $100.00. The cap is the only
    thing standing between a judgement and a payout, which is why this matters more than it
    used to.
    """
    whey = OrderLineItem(
        name="2.5LBS White Chocolate Raspberry Huge Whey",
        sku="0159",
        quantity=4,
        unit_price=Decimal("59.99"),
    )
    order = Order(order_id="337761802", user_id="334430", line_items=(whey,))
    line = claim_lines(ClaimedProduct(name=whey.name, quantity=4, sku="0159"), order=order)[0]
    conclusion = a_conclusion(
        damaged_items=(DamagedItem(product_name=whey.name, quantity=4, sku="0159"),),
        recommended_amount_usd="180.00",
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        line=line,
        order=order,
        invoice=Invoice(invoice_id="INV-337761802", line_items=(whey,)),
    )

    assert result.amount.proposed_usd == Decimal("180.00")
    assert result.amount.amount_usd == Decimal("100.00")
    assert result.amount.cap_applied is True
    assert result.drafted_email is not None
    assert "$100.00" in result.drafted_email.body
    # The merchant reads the figure that survived the cap, never the one proposed. This is
    # the rule about money that did not change when FR-1.21 was reversed.
    assert "180.00" not in result.drafted_email.body


async def test_the_figure_is_worked_out_from_the_invoice_and_never_from_what_the_model_wrote() -> (
    None
):
    """FR-1.21: the model says what was damaged; code says how much.

    The investigation is scripted to claim a figure of its own in its reasoning. It has
    no field to put one in, and nothing reads one out of its words: the recommended
    amount is the invoice's price for the product it named, and the figure in the email
    is that one.
    """
    conclusion = a_conclusion(
        reasoning="The bottle is crushed. I would put it at about $12.00.",
        concerns=("I am not certain the $12.00 I have in mind is the right price.",),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.amount.amount_usd == Decimal("40.00")
    assert result.amount.priced_from == "INV-342578703"
    assert [component.unit_price for component in result.amount.components] == [Decimal("52.00")]
    assert result.drafted_email is not None
    # The figure comes from the amount field, never from a number said in passing.
    assert "12.00" not in result.drafted_email.body
    assert "$40.00" in result.drafted_email.body
    assert "$40.00" in result.drafted_email.body


async def test_an_email_carrying_a_figure_the_model_wrote_is_refused_and_goes_to_a_person() -> None:
    """FR-1.21, NFR-4: wording that breaks the money rule is refused rather than repaired.

    A representative is never shown the wording, the line goes to a person, and what the
    investigation recommended is kept beside it so the refusal can be understood.
    """
    conclusion = a_conclusion(
        email_body="We have looked at your claim and will refund $52.00 for the collagen."
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.drafted_email is None
    assert result.conclusion is not None
    assert result.conclusion.recommendation is Recommendation.APPROVE
    assert any("amount of money" in concern for concern in result.concerns)


async def test_an_approval_withheld_for_missing_evidence_requests_it_without_money() -> None:
    """FR-1.6, FR-1.21: a merchant request never promises an unapproved amount."""
    conclusion = a_conclusion(
        evidence=evidence_all_in_hand(customer_confirmation=EvidenceState.MISSING)
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.drafted_email is not None
    assert "additional information" in result.drafted_email.body
    assert "customer who received the parcel" in result.drafted_email.body
    assert "$40.00" not in result.drafted_email.body
    assert AMOUNT_PLACEHOLDER not in result.drafted_email.body


# --- The shared evidence is settled once for the claim (FR-1a.3) ------------


async def test_what_the_claim_settled_about_the_parcel_stands_over_this_run_s_own_read() -> None:
    """FR-1a.3: two products on one claim can never disagree about the same photograph.

    The invoice, the customer confirmation and the photograph of the box describe the
    parcel rather than any one product, so they are settled once and every product is
    handed the same answer. Where this run read one of them differently, the claim's
    answer stands and the disagreement is reported rather than dropped.
    """
    conclusion = a_conclusion(**an_email_with_no_figure())

    result = await investigate(
        a_run_that_concludes(conclusion),
        shared_evidence=(settled(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.MISSING),),
    )

    assert state_of(result, EvidenceKind.OUTER_PACKAGING_PHOTO) is EvidenceState.MISSING
    assert any("outer packaging photo" in concern for concern in result.concerns)
    assert result.outcome.recommendation is Recommendation.REQUEST_INFO


async def test_the_photographs_of_the_damage_are_this_product_s_own() -> None:
    """FR-1a.3: only three of the four are settled for the whole claim.

    Photographs of the damage are per product, so what this run found about them is what
    is recorded, even when a caller hands over a settled answer about them by mistake.
    """
    result = await investigate(
        a_run_that_concludes(a_conclusion()),
        shared_evidence=(settled(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.MISSING),),
    )

    assert state_of(result, EvidenceKind.DAMAGED_PRODUCT_PHOTO) is EvidenceState.PRESENT
    assert result.outcome.recommendation is Recommendation.APPROVE


# --- One product, whatever else was claimed (FR-1b.1, FR-1b.2, FR-1b.4) -----


async def test_the_run_sees_the_whole_claim_and_answers_for_one_product() -> None:
    """FR-1b.2: the merchant's account, the order and the other products all go in.

    A photograph can show two broken items and the description is the only account
    anybody has of what happened, so the run is shown everything — and answers for the
    product it was given.
    """
    mine, others = the_collagen_beside(five_other_products())
    model = a_run_that_concludes(a_conclusion())

    result = await investigate(model, line=mine, siblings=others)

    asked = model.asked[0].text
    assert "1 order affected" in asked
    assert AMPOULE in asked
    assert "Duck Neck Crunchies" in asked
    assert result.line.claim_line_id == mine.claim_line_id
    assert result.line.product_name == COLLAGEN


async def test_a_product_reaches_the_same_answer_alone_as_it_does_beside_five_others() -> None:
    """FR-1b.4: what else was claimed changes nothing about this product's own answer.

    The same product with the same evidence is investigated twice — once as the only
    thing on the claim, once beside five other damaged products. The evidence, the
    judgements, the recommendation and the figure all come out identical.

    What this shows is that nothing in our own code carries another product's facts into
    this one's answer. It cannot show that a real model would answer identically: the two
    runs are asked slightly different questions, because the requirements insist the
    other products are named (FR-1b.2). What is pinned down is that the difference stops
    at the question.
    """
    mine, others = the_collagen_beside(five_other_products())

    alone = await investigate(a_run_that_concludes(a_conclusion()))
    crowded = await investigate(a_run_that_concludes(a_conclusion()), line=mine, siblings=others)

    assert alone.evidence == crowded.evidence
    assert alone.assessments == crowded.assessments
    assert alone.outcome.recommendation == crowded.outcome.recommendation
    assert alone.amount == crowded.amount
    assert alone.drafted_email == crowded.drafted_email
    assert alone.concerns == crowded.concerns


async def test_the_order_the_other_products_arrive_in_changes_nothing_that_is_asked() -> None:
    """FR-1b.4, NFR-1: the question is fixed, so it cannot depend on how a list was built.

    The same six-product claim is handed over twice with the other five in opposite
    orders. The words put to the model are identical, down to the character.
    """
    mine, others = the_collagen_beside(five_other_products())

    forwards = a_run_that_concludes(a_conclusion())
    backwards = a_run_that_concludes(a_conclusion())
    await investigate(forwards, line=mine, siblings=others)
    await investigate(backwards, line=mine, siblings=tuple(reversed(others)))

    assert forwards.asked[0].text == backwards.asked[0].text


async def test_a_product_is_never_listed_among_its_own_siblings() -> None:
    """FR-1b.4: handing over the whole claim asks the same question as handing over the rest.

    A caller that passes every line of the claim, this one included, must not have the
    product described to the run twice — once as its own and once as somebody else's.
    """
    mine, others = the_collagen_beside(five_other_products())

    given_the_others = a_run_that_concludes(a_conclusion())
    given_everything = a_run_that_concludes(a_conclusion())
    await investigate(given_the_others, line=mine, siblings=others)
    await investigate(given_everything, line=mine, siblings=(mine, *others))

    assert given_the_others.asked[0].text == given_everything.asked[0].text


async def test_another_product_s_photographs_never_reach_this_run_s_question() -> None:
    """FR-1b.4: which images were tied to a product depends on how the claim was split.

    It is the one fact about another product that can change with the split, so it is the
    one fact left out of what this run is told about them.
    """
    mine, others = the_collagen_beside(five_other_products())
    with_photographs = tuple(
        other.model_copy(update={"damage_attachment_ids": ("ATT-ONLY-ON-THE-OTHER-PRODUCT",)})
        for other in others
    )

    model = a_run_that_concludes(a_conclusion())
    await investigate(model, line=mine, siblings=with_photographs)

    assert "ATT-ONLY-ON-THE-OTHER-PRODUCT" not in model.asked[0].text


# --- The same claim, twice (NFR-1) ------------------------------------------


async def test_the_same_claim_investigated_twice_produces_the_same_write_up() -> None:
    """NFR-1: the same claim, investigated twice, produces the same report.

    Everything after the model's answer is arithmetic and rules, so two runs given the
    same answer agree on every part of the write-up: the findings, the judgements, the
    recommendation, the figure, the concerns and the email.
    """
    first = await investigate(a_run_that_concludes(a_conclusion()))
    second = await investigate(a_run_that_concludes(a_conclusion()))

    assert first == second


# --- Narrating the run (NFR-3) ----------------------------------------------


async def test_the_run_says_which_product_it_started_and_what_it_recommends() -> None:
    """NFR-3: somebody watching can tell which product is being worked on, and how it ended.

    Several products are investigated at once, so every message names the product it
    belongs to. No message carries a figure: money reaches a screen only in a finished
    write-up, where it was arithmetic rather than wording.
    """
    events = EventStream()

    result = await investigate(a_run_that_concludes(a_conclusion()), events=events)

    said = {event.kind: event for event in events.events()}
    assert said[EventKind.LINE_STARTED].claim_line_id == result.line.claim_line_id
    assert COLLAGEN in said[EventKind.LINE_STARTED].summary
    assert said[EventKind.LINE_FINISHED].detail["recommendation"] == Recommendation.APPROVE.value
    assert "52.00" not in said[EventKind.LINE_FINISHED].summary


# --- The run is told how alike claims were decided (FR-S.6) -----------------


def a_closed_claim(**overrides: object) -> PrecedentRecord:
    """One past claim, already decided by a representative."""
    fields: dict[str, object] = {
        "precedent_id": "PREC-CASE-0900-L01",
        "case_id": "CASE-0900",
        "claim_line_id": "CASE-0900-L01",
        "user_id": "283959",
        "product_name": "Liposomal Tripeptide Collagen",
        "sku": "COLLAGEN1",
        "unit_price": Decimal("52.00"),
        "merchant_account": "The bottle arrived cracked in a crushed box.",
        "match": MatchOutcome.MATCHED,
        "evidence": (),
        "assessments": (),
        "outcome": Recommendation.REQUEST_REP_CLARIFICATION,
        "amount_usd": None,
        "cap_applied": False,
        "rep_note": "Refused: the crushing happened after delivery.",
        "withdrawn": False,
        "closed_at": datetime(2026, 1, 8, tzinfo=UTC),
    }
    fields.update(overrides)
    return PrecedentRecord(**fields)


def a_precedent_set(*records: PrecedentRecord) -> PrecedentSet:
    """A retrieved set carrying the given closed claims."""
    return PrecedentSet(
        retrieved=tuple(
            RetrievedPrecedent(
                record=record,
                similarity=PrecedentSimilarity(
                    score=0.9, reasons=("the product names share: collagen",)
                ),
            )
            for record in records
        ),
        considered=len(records),
    )


def what_the_model_was_asked(model: ScriptedModel) -> str:
    """Every word the run put in front of the model on its opening turn."""
    return model.asked[0].text


async def test_fr_s_6_a_run_is_handed_the_closed_claims_most_like_its_product() -> None:
    """FR-S.6: precedent arrives with the claim; the model never goes looking for it.

    This is the wiring the whole feature turns on. Everything else can work — the store,
    the comparison, the endpoint — and the investigation still be none the wiser, which
    is exactly where this stood before.
    """
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=a_precedent_set(a_closed_claim()))

    asked = what_the_model_was_asked(model)
    assert "## SIMILAR CLAIMS HANDLED BEFORE" in asked
    assert "CASE-0900" in asked
    assert "closed as: request_rep_clarification" in asked
    assert "the crushing happened after delivery" in asked


async def test_fr_s_13_a_run_told_nothing_about_precedent_is_not_told_there_is_none() -> None:
    """FR-S.13: "nobody looked" and "we looked and found none" must not read alike."""
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=None)

    # The heading, not the phrase: the fixed rules always mention similar claims, and
    # this is about whether any records were put under them.
    assert "## SIMILAR CLAIMS HANDLED BEFORE" not in what_the_model_was_asked(model)


async def test_fr_s_13_a_run_is_told_when_the_store_was_read_and_held_nothing() -> None:
    """FR-S.13: an empty answer is a fact about the store, and the run is told it."""
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=a_precedent_set())

    assert "holds nothing much like this one" in what_the_model_was_asked(model)


async def test_fr_1_21_what_past_claims_were_settled_for_is_shown_to_the_model() -> None:
    """FR-1.21, FR-S.6: the model decides the amount, so it is shown what alike claims paid.

    This is the reverse of what it used to assert. While no figure could come from model
    output, past amounts were stored and deliberately never rendered — a model forbidden to
    write a figure must not be shown one. The model now decides the amount and is asked to
    weigh how comparable claims were settled, so withholding the figures would leave that
    instruction with nothing behind it.
    """
    model = a_run_that_concludes(a_conclusion())

    await investigate(
        model,
        precedent=a_precedent_set(
            a_closed_claim(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00"))
        ),
    )

    asked = what_the_model_was_asked(model)
    section = asked[asked.index("## SIMILAR CLAIMS HANDLED BEFORE") :]
    assert "52.00" in section


async def test_fr_1_8_to_fr_1_11_all_four_judgements_come_back_with_their_reasoning() -> None:
    """FR-1.8, FR-1.9, FR-1.10, FR-1.11: four questions, each answered and each explained.

    Is the damage actually visible; can the damaged product be identified; does that
    product appear on the invoice; was the outer packaging photographed. They are
    assessments the system reports with its reasoning, not verdicts that settle the
    claim, so every one of them has to arrive with words a representative can disagree
    with and a confidence they can weigh (FR-2.3, NFR-3).

    All four are reported whatever they found, in a fixed order, so a representative
    sees what was considered rather than inferring it from silence.
    """
    result = await investigate(a_run_that_concludes(a_conclusion(assessments=all_four_answered())))

    answered = {assessment.name: assessment for assessment in result.assessments}
    assert tuple(answered) == REQUIRED_ASSESSMENTS

    for name in REQUIRED_ASSESSMENTS:
        judgement = answered[name]
        assert judgement.reasoning.strip(), f"{name} was answered with no reasoning"
        assert 0.0 <= judgement.confidence <= 1.0


async def test_fr_1_9_a_product_that_cannot_be_identified_is_not_paid_for() -> None:
    """FR-1.9, FR-1.13: if the damaged product cannot be told apart, the amount cannot be worked out.

    So the claim goes back to the merchant naming what would settle it, rather than the
    likelier of two candidates being chosen. Choosing would invent the payout.
    """
    result = await investigate(
        a_run_that_concludes(
            a_conclusion(
                assessments=all_four_answered(product_identifiable=False),
                recommendation=Recommendation.APPROVE,
                **an_email_with_no_figure(),
            )
        )
    )

    assert result.outcome.recommendation is not Recommendation.APPROVE
    identified = next(
        assessment
        for assessment in result.assessments
        if assessment.name is AssessmentName.PRODUCT_IDENTIFIABLE
    )
    assert identified.passed is False
