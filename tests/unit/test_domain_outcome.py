"""What is recommended for one claim line once the rules have had their say.

The rule these tests exist to pin down runs in one direction only: code may
withhold a payment the requirements forbid, and may never move a recommendation
towards paying. So most of these tests start from an investigation that wanted to
pay and check that something stopped it — and a handful check the opposite, that a
refusal or a hand-off to a person is left exactly as the investigation left it
(FR-1.14).

Every input is built by hand here. The function reads nothing but its arguments:
no clock, no network, no model, and nothing at all about the other claim lines in
the claim, which is what makes a line decide the same way whether it was claimed
alone or alongside five others (FR-1b.4, NFR-1).
"""

from __future__ import annotations

from decimal import Decimal

from claim_agent.domain.assessment import Assessment, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import OrderLineItem
from claim_agent.domain.outcome import (
    _WITHHELD_RECOMMENDATION,
    OutcomeDecision,
    OverrideReason,
    Recommendation,
    decide_outcome,
)
from claim_agent.domain.reimbursement import AmountComponent, AmountDerivation
from claim_agent.policy import Policy

COLLAGEN = "Liposomal Tripeptide Collagen"


def finding(kind: EvidenceKind, state: EvidenceState) -> EvidenceFinding:
    """What was found for one piece of evidence, in whichever of the four states."""
    return EvidenceFinding(
        kind=kind,
        state=state,
        observed="What the investigation says it saw.",
        attachment_id=None if state is EvidenceState.MISSING else "att-1",
        problem=(
            None
            if state in (EvidenceState.PRESENT, EvidenceState.MISSING)
            else "Why it cannot be relied on."
        ),
    )


def all_evidence_present() -> tuple[EvidenceFinding, ...]:
    """All four pieces of evidence there and usable — the only state that can be paid on."""
    return tuple(finding(kind, EvidenceState.PRESENT) for kind in REQUIRED_EVIDENCE)


def evidence_with(kind: EvidenceKind, state: EvidenceState) -> tuple[EvidenceFinding, ...]:
    """All four pieces of evidence, with one of them in a state that is not usable."""
    return tuple(
        finding(each, state if each is kind else EvidenceState.PRESENT)
        for each in REQUIRED_EVIDENCE
    )


def assessment(name: AssessmentName, *, passed: bool = True, confidence: float = 0.9) -> Assessment:
    """One of the four judgements made once the evidence was in hand."""
    return Assessment(
        name=name,
        passed=passed,
        reasoning="Why the investigation reached this answer.",
        confidence=confidence,
        attachment_ids=("att-1",),
    )


def all_questions_answered(*, confidence: float = 0.9) -> tuple[Assessment, ...]:
    """All four questions answered yes, each as sure as asked for."""
    return tuple(assessment(name, confidence=confidence) for name in AssessmentName)


def matched_line() -> ClaimLine:
    """A claim line whose product is exactly one line on the order, so it has one price."""
    return ClaimLine(
        claim_line_id="CASE-1001-L01",
        claimed=ClaimedProduct(name=COLLAGEN, quantity=1, sku="COLLAGEN1"),
        match=MatchOutcome.MATCHED,
        order_line=OrderLineItem(
            name=COLLAGEN, sku="COLLAGEN1", quantity=1, unit_price=Decimal("52.00")
        ),
    )


def unmatched_line(match: MatchOutcome) -> ClaimLine:
    """A claim line whose product could not be tied to exactly one line on the order."""
    return ClaimLine(
        claim_line_id="CASE-1002-L01",
        claimed=ClaimedProduct(name="CleanBoss 24oz bottle", quantity=1),
        match=match,
    )


def amount_of_nothing(
    *, priced_from: str | None, components: tuple[AmountComponent, ...] = ()
) -> AmountDerivation:
    """An amount that came to nothing, in one of the three ways that can happen."""
    return AmountDerivation(
        components=components,
        items_total_usd=Decimal("0.00"),
        refund_percentage=60,
        subtotal_usd=Decimal("0.00"),
        amount_usd=Decimal("0.00"),
        cap_usd=Decimal("100.00"),
        cap_applied=False,
        priced_from=priced_from,
    )


PAYABLE_AMOUNT = AmountDerivation(
    components=(
        AmountComponent(
            product_name=COLLAGEN,
            quantity=1,
            unit_price=Decimal("52.00"),
            refunded_usd=Decimal("52.00"),
            sku="COLLAGEN1",
        ),
    ),
    items_total_usd=Decimal("52.00"),
    refund_percentage=100,
    subtotal_usd=Decimal("52.00"),
    amount_usd=Decimal("52.00"),
    cap_usd=Decimal("100.00"),
    cap_applied=False,
    priced_from="INV-342578703",
)
"""An amount with something in it to pay: one item at the invoice price, under the cap.

One shared value rather than one per test, because it never changes — every shape in
this project refuses to be modified after it is built.
"""


def decide(
    recommended: Recommendation,
    *,
    evidence: tuple[EvidenceFinding, ...] | None = None,
    assessments: tuple[Assessment, ...] | None = None,
    line: ClaimLine | None = None,
    amount: AmountDerivation | None = PAYABLE_AMOUNT,
    policy: Policy | None = None,
    budget_exhausted: bool = False,
) -> OutcomeDecision:
    """Decide one claim line, defaulting everything a test does not care about to clean.

    Clean means: all four pieces of evidence present, all four questions answered yes and
    confidently, the product matched to one order line, and a payable amount. A test that
    cares about one of those replaces only that one, so what it is testing is the only
    thing on the page.

    Passing `amount=None` means no amount was worked out at all, which is why the clean
    amount is the default value rather than something chosen when nothing was passed.
    """
    return decide_outcome(
        recommended,
        evidence=all_evidence_present() if evidence is None else evidence,
        assessments=all_questions_answered() if assessments is None else assessments,
        line=matched_line() if line is None else line,
        amount=amount,
        policy=Policy() if policy is None else policy,
        budget_exhausted=budget_exhausted,
    )


# ---------------------------------------------------------------------------
# What the investigation says stands (FR-1.14)
# ---------------------------------------------------------------------------


def test_fr_1_14_a_well_evidenced_approval_is_left_exactly_as_it_was_recommended() -> None:
    """Nothing here second-guesses an approval the requirements do not forbid."""
    decision = decide(Recommendation.APPROVE)

    assert decision.recommendation is Recommendation.APPROVE
    assert decision.recommended_by_agent is Recommendation.APPROVE
    assert decision.overrides == ()
    assert not decision.was_overridden
    assert "paying this line" in decision.explanation
    assert "none of the rules changed that" in decision.explanation


def test_fr_1_14_a_recommendation_to_refuse_the_claim_is_the_investigations_to_make() -> None:
    """Refusing is a judgement about the merits, and no rule here makes judgements."""
    decision = decide(
        Recommendation.DENY,
        evidence=(),
        assessments=(),
        line=unmatched_line(MatchOutcome.NOT_ON_ORDER),
        amount=None,
    )

    assert decision.recommendation is Recommendation.DENY
    assert decision.overrides == ()
    assert "refusing this line" in decision.explanation


def test_fr_1_14_a_recommendation_to_go_back_to_the_merchant_passes_through_untouched() -> None:
    """The rules only ever withhold a payment; there is no payment here to withhold."""
    decision = decide(Recommendation.REQUEST_INFO, evidence=(), assessments=(), amount=None)

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == ()


def test_fr_1_14_a_recommendation_to_hand_the_claim_to_a_person_passes_through_untouched() -> None:
    """Escalating is already the most cautious answer, so nothing can improve on it."""
    decision = decide(Recommendation.ESCALATE, evidence=(), assessments=(), amount=None)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == ()


def test_fr_1_15_a_refusal_made_on_thin_confidence_is_still_the_investigations_to_make() -> None:
    """Never approving under uncertainty is a rule about approving, and about nothing else."""
    decision = decide(Recommendation.DENY, assessments=all_questions_answered(confidence=0.1))

    assert decision.recommendation is Recommendation.DENY
    assert decision.overrides == ()


# ---------------------------------------------------------------------------
# The two rules that apply whatever was recommended (FR-1.16, NFR-4)
# ---------------------------------------------------------------------------


def test_fr_1_16_a_run_that_ran_out_of_steps_goes_to_a_person_however_clean_the_claim() -> None:
    """A run that did not finish has not established a payment, whatever it managed to say."""
    decision = decide(Recommendation.APPROVE, budget_exhausted=True)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)
    assert "ran out of steps" in decision.explanation


def test_fr_1_16_what_the_investigation_established_is_carried_forward_not_thrown_away() -> None:
    """A rep is not handed an empty result: what was recommended is still on the decision."""
    decision = decide(Recommendation.APPROVE, budget_exhausted=True)

    assert decision.recommended_by_agent is Recommendation.APPROVE


def test_fr_1_16_running_out_of_steps_overrides_even_a_recommendation_to_refuse() -> None:
    """An unfinished run has not established a refusal either, so a person decides."""
    decision = decide(Recommendation.DENY, budget_exhausted=True)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)


def test_fr_1_16_a_run_that_had_already_escalated_says_so_without_claiming_a_change() -> None:
    """The recommendation did not change, so the sentence must not say it did."""
    decision = decide(Recommendation.ESCALATE, budget_exhausted=True)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)
    assert "instead" not in decision.explanation
    assert "the same recommendation" in decision.explanation


def test_nfr_4_evidence_we_could_not_read_ourselves_goes_to_a_person() -> None:
    """Our own failed download is our problem, and a person can act on it."""
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert OverrideReason.EVIDENCE_UNREADABLE in decision.overrides
    assert "could not read the damaged product photo" in decision.explanation


def test_fr_1_7_a_merchant_is_never_asked_for_something_only_we_could_fix() -> None:
    """A request they cannot act on is worse than no request at all."""
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert "the merchant" not in decision.explanation


def test_nfr_4_evidence_we_could_not_read_goes_to_a_person_even_after_a_refusal() -> None:
    """A conclusion drawn without being able to see the evidence is not a conclusion."""
    decision = decide(
        Recommendation.DENY,
        evidence=evidence_with(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.EVIDENCE_UNREADABLE,)


# ---------------------------------------------------------------------------
# Evidence that is not all in hand (FR-1.5, FR-1.6)
# ---------------------------------------------------------------------------


def test_fr_1_6_a_missing_photograph_sends_the_claim_back_to_the_merchant() -> None:
    """The system asks and waits rather than approving on three quarters of the evidence."""
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.MISSING),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    assert "damaged product photo" in decision.explanation


def test_fr_1_5_evidence_that_arrived_unusable_counts_as_not_having_it() -> None:
    """A photograph too dark to draw a conclusion from does not satisfy its requirement."""
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.UNUSABLE),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert "outer packaging photo" in decision.explanation


def test_fr_1_6_evidence_nobody_looked_for_is_not_evidence_we_have() -> None:
    """CASE-1005 has no attachments at all: all four items are missing and it must not error."""
    decision = decide(Recommendation.APPROVE, evidence=())

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    for kind in REQUIRED_EVIDENCE:
        assert kind.replace("_", " ") in decision.explanation


# ---------------------------------------------------------------------------
# The four questions (FR-1.12)
# ---------------------------------------------------------------------------


def test_fr_1_12_a_question_answered_no_sends_the_claim_back_to_the_merchant() -> None:
    """Naming which question failed is the point: a vague request costs another round trip."""
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
        assessment(AssessmentName.PRODUCT_ON_INVOICE),
        assessment(AssessmentName.PACKAGING_DOCUMENTED),
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    assert "answered no on damage visible" in decision.explanation


def test_fr_1_12_a_question_that_was_never_answered_is_not_a_question_that_passed() -> None:
    """An incomplete investigation must never read as a clean one.

    And it goes to a person, not to the merchant: a question our run never got round
    to answering is our shortcoming, and there is nothing to ask the merchant for
    (NFR-4).
    """
    answers = tuple(
        assessment(name)
        for name in AssessmentName
        if name is not AssessmentName.PACKAGING_DOCUMENTED
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.INVESTIGATION_INCOMPLETE,)
    assert "never answered packaging documented" in decision.explanation


def test_fr_1_12_a_failed_question_and_an_unanswered_one_are_both_reported() -> None:
    """Two different problems, and a rep should not have to discover the second later."""
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    # A question answered no is the merchant's to act on; a question never answered is
    # ours. Both are reported, and the more cautious of the two recommendations stands.
    assert decision.recommendation is Recommendation.ESCALATE
    assert set(decision.overrides) == {
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.INVESTIGATION_INCOMPLETE,
    }
    assert "answered no on damage visible" in decision.explanation
    assert "never answered product on invoice and packaging documented" in decision.explanation


# ---------------------------------------------------------------------------
# Confidence (FR-1.15)
# ---------------------------------------------------------------------------


def test_fr_1_15_confidence_below_the_threshold_hands_the_claim_to_a_person() -> None:
    """A claim is only as well established as its weakest judgement."""
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, confidence=0.5),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
        assessment(AssessmentName.PRODUCT_ON_INVOICE),
        assessment(AssessmentName.PACKAGING_DOCUMENTED),
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.NOT_CONFIDENT_ENOUGH,)
    assert "0.50" in decision.explanation
    assert "0.70" in decision.explanation


def test_fr_1_15_confidence_landing_exactly_on_the_threshold_is_confident_enough() -> None:
    """The threshold is the lowest a payment may rest on, not the first figure above it."""
    decision = decide(
        Recommendation.APPROVE,
        assessments=all_questions_answered(confidence=0.7),
        policy=Policy(min_assessment_confidence=0.7),
    )

    assert decision.recommendation is Recommendation.APPROVE
    assert decision.overrides == ()


def test_fr_1_15_the_confidence_threshold_comes_from_the_claim_policy() -> None:
    """The figure is a provisional judgement call, so it has to be changeable (NFR-7)."""
    decision = decide(
        Recommendation.APPROVE,
        assessments=all_questions_answered(confidence=0.9),
        policy=Policy(min_assessment_confidence=0.95),
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert OverrideReason.NOT_CONFIDENT_ENOUGH in decision.overrides


def test_fr_1_15_an_investigation_that_assessed_nothing_has_cleared_nothing() -> None:
    """No confidence to test is not the same as being confident, and must not read as it."""
    decision = decide(Recommendation.APPROVE, assessments=())

    assert decision.recommendation is Recommendation.ESCALATE
    assert OverrideReason.NOT_CONFIDENT_ENOUGH in decision.overrides
    # A run that answered none of the four questions did not finish, which is a
    # statement about our own investigation rather than about the merchant's evidence.
    assert OverrideReason.INVESTIGATION_INCOMPLETE in decision.overrides
    assert "nothing was assessed" in decision.explanation


# ---------------------------------------------------------------------------
# A product with no single price (FR-1.13, FR-1a.2, FR-1.21)
# ---------------------------------------------------------------------------


def test_fr_1_13_a_product_matching_two_order_lines_is_never_priced_by_choosing_one() -> None:
    """CleanBoss's order holds two 24oz bottles at two prices; a photograph cannot separate them."""
    decision = decide(
        Recommendation.APPROVE, line=unmatched_line(MatchOutcome.AMBIGUOUS), amount=None
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "more than one line on the order" in decision.explanation


def test_fr_1a_2_a_product_that_is_not_on_the_order_cannot_be_reimbursed() -> None:
    """A claim for something never bought is a finding, and never a payment."""
    decision = decide(
        Recommendation.APPROVE, line=unmatched_line(MatchOutcome.NOT_ON_ORDER), amount=None
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "not on the order" in decision.explanation


def test_fr_1_21_an_approval_with_no_amount_worked_out_goes_to_a_person() -> None:
    """No figure means nothing to approve, and the gap is never filled by guessing."""
    decision = decide(Recommendation.APPROVE, amount=None)

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "no amount was worked out" in decision.explanation


def test_fr_1_18_an_approval_with_no_invoice_to_price_from_says_so() -> None:
    """A rep can chase a missing invoice, so the reason has to reach them."""
    decision = decide(Recommendation.APPROVE, amount=amount_of_nothing(priced_from=None))

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "no invoice to price it from" in decision.explanation


def test_fr_1_18_an_approval_whose_product_was_not_on_the_invoice_names_the_invoice() -> None:
    """The invoice that was read is named, so a rep can look at the same document."""
    decision = decide(Recommendation.APPROVE, amount=amount_of_nothing(priced_from="INV-342578703"))

    assert decision.recommendation is Recommendation.ESCALATE
    assert "nothing could be priced from invoice INV-342578703" in decision.explanation


def test_fr_1_20_an_item_the_invoice_prices_at_nothing_goes_to_a_person() -> None:
    """A free promotional insert really exists in this data, and no requirement covers it."""
    free_item = AmountComponent(
        product_name="Insert Card",
        quantity=1,
        unit_price=Decimal("0.00"),
        refunded_usd=Decimal("0.00"),
        sku="Insert",
    )

    decision = decide(
        Recommendation.APPROVE,
        amount=amount_of_nothing(priced_from="INV-342578703", components=(free_item,)),
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert "prices the damaged product at nothing" in decision.explanation


# ---------------------------------------------------------------------------
# Several rules at once (NFR-3, NFR-4)
# ---------------------------------------------------------------------------


def test_nfr_4_the_most_cautious_recommendation_wins_when_two_rules_disagree() -> None:
    """Missing evidence asks the merchant and thin confidence asks a person; a person wins."""
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, confidence=0.2),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
        assessment(AssessmentName.PRODUCT_ON_INVOICE),
        assessment(AssessmentName.PACKAGING_DOCUMENTED),
    )

    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.MISSING),
        assessments=answers,
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.NOT_CONFIDENT_ENOUGH,
    )


def test_nfr_3_every_rule_that_stepped_in_is_reported_and_not_only_the_first() -> None:
    """A rep should see everything that is wrong with a line, not fix one and find the next."""
    evidence = (
        finding(EvidenceKind.INVOICE, EvidenceState.MISSING),
        finding(EvidenceKind.CUSTOMER_CONFIRMATION, EvidenceState.UNREADABLE),
    )
    answers = (assessment(AssessmentName.DAMAGE_VISIBLE, passed=False, confidence=0.3),)

    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence,
        assessments=answers,
        line=unmatched_line(MatchOutcome.NOT_ON_ORDER),
        amount=None,
        budget_exhausted=True,
    )

    assert decision.recommendation is Recommendation.ESCALATE
    assert decision.overrides == (
        OverrideReason.BUDGET_EXHAUSTED,
        OverrideReason.EVIDENCE_UNREADABLE,
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.INVESTIGATION_INCOMPLETE,
        OverrideReason.NOT_CONFIDENT_ENOUGH,
        OverrideReason.PRODUCT_NOT_PRICEABLE,
    )


def test_nfr_3_a_reason_two_rules_agree_on_is_listed_once_and_explained_twice() -> None:
    """Both the evidence and the questions were short; one reason, two things to fix."""
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
        assessment(AssessmentName.PRODUCT_ON_INVOICE),
        assessment(AssessmentName.PACKAGING_DOCUMENTED),
    )

    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.MISSING),
        assessments=answers,
    )

    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    assert "the merchant has still to supply the invoice" in decision.explanation
    assert "answered no on damage visible" in decision.explanation


def test_nfr_1_the_same_claim_line_always_reaches_the_same_decision() -> None:
    """Two identical claims have to arrive at a rep looking identical."""
    first = decide(Recommendation.APPROVE, evidence=(), assessments=(), amount=None)
    second = decide(Recommendation.APPROVE, evidence=(), assessments=(), amount=None)

    assert first == second


def test_nfr_4_a_shortcoming_of_ours_never_sends_a_request_to_the_merchant() -> None:
    """The merchant may only ever be asked for something they can actually supply.

    Two of the reasons a payment is withheld are faults on our side rather than gaps in
    what the merchant sent: an image we could not read, and a question our own run never
    answered. Neither may end in a request to the merchant, because there is nothing
    they could send that would help — the pre-flight screen already has one label that
    makes exactly this mistake, and DESIGN.md records it as a fault rather than a
    pattern to copy.

    Written against the mapping itself rather than by working through cases, so that a
    reason added later cannot quietly be given the merchant's remedy (NFR-4).
    """
    ours_to_fix = {
        OverrideReason.EVIDENCE_UNREADABLE,
        OverrideReason.INVESTIGATION_INCOMPLETE,
        OverrideReason.BUDGET_EXHAUSTED,
    }

    for reason in ours_to_fix:
        assert _WITHHELD_RECOMMENDATION[reason] is not Recommendation.REQUEST_INFO

    # And the merchant's own remedy is reserved for the one reason they can act on.
    asks_the_merchant = {
        reason
        for reason, outcome in _WITHHELD_RECOMMENDATION.items()
        if outcome is Recommendation.REQUEST_INFO
    }
    assert asks_the_merchant == {OverrideReason.EVIDENCE_INCOMPLETE}
