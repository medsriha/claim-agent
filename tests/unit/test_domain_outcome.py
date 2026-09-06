from __future__ import annotations

from collections.abc import Sequence
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
    return tuple(finding(kind, EvidenceState.PRESENT) for kind in REQUIRED_EVIDENCE)


def evidence_with(kind: EvidenceKind, state: EvidenceState) -> tuple[EvidenceFinding, ...]:
    return tuple(
        finding(each, state if each is kind else EvidenceState.PRESENT)
        for each in REQUIRED_EVIDENCE
    )


def assessment(name: AssessmentName, *, passed: bool = True) -> Assessment:
    return Assessment(
        name=name,
        passed=passed,
        reasoning="Why the investigation reached this answer.",
        attachment_ids=("att-1",),
    )


def all_questions_answered() -> tuple[Assessment, ...]:
    return tuple(assessment(name) for name in AssessmentName)


def matched_line() -> ClaimLine:
    return ClaimLine(
        claim_line_id="CASE-1001-L01",
        claimed=ClaimedProduct(name=COLLAGEN, quantity=1, sku="COLLAGEN1"),
        match=MatchOutcome.MATCHED,
        order_line=OrderLineItem(
            name=COLLAGEN, sku="COLLAGEN1", quantity=1, unit_price=Decimal("52.00")
        ),
    )


def unmatched_line(match: MatchOutcome) -> ClaimLine:
    return ClaimLine(
        claim_line_id="CASE-1002-L01",
        claimed=ClaimedProduct(name="CleanBoss 24oz bottle", quantity=1),
        match=match,
    )


def amount_of_nothing(
    *, priced_from: str | None, components: tuple[AmountComponent, ...] = ()
) -> AmountDerivation:
    return AmountDerivation(
        components=components,
        items_total_usd=Decimal("0.00"),
        proposed_usd=Decimal("0.00"),
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
            sku="COLLAGEN1",
        ),
    ),
    items_total_usd=Decimal("52.00"),
    proposed_usd=Decimal("52.00"),
    amount_usd=Decimal("52.00"),
    cap_usd=Decimal("100.00"),
    cap_applied=False,
    priced_from="INV-342578703",
)


def decide(
    recommended: Recommendation,
    *,
    evidence: tuple[EvidenceFinding, ...] | None = None,
    assessments: tuple[Assessment, ...] | None = None,
    lines: Sequence[ClaimLine] | None = None,
    amount: AmountDerivation | None = PAYABLE_AMOUNT,
    policy: Policy | None = None,
    budget_exhausted: bool = False,
    requested_details: tuple[str, ...] = (),
) -> OutcomeDecision:
    return decide_outcome(
        recommended,
        evidence=all_evidence_present() if evidence is None else evidence,
        assessments=all_questions_answered() if assessments is None else assessments,
        lines=(matched_line(),) if lines is None else lines,
        amount=amount,
        policy=Policy() if policy is None else policy,
        budget_exhausted=budget_exhausted,
        requested_details=requested_details,
    )


def test_fr_1_14_a_well_evidenced_approval_is_left_exactly_as_it_was_recommended() -> None:
    decision = decide(Recommendation.APPROVE)

    assert decision.recommendation is Recommendation.APPROVE
    assert decision.recommended_by_agent is Recommendation.APPROVE
    assert decision.overrides == ()
    assert not decision.was_overridden
    assert "paying this claim" in decision.explanation
    assert "none of the rules changed that" in decision.explanation


def test_fr_1_14_a_request_for_rep_clarification_passes_through_untouched() -> None:
    decision = decide(
        Recommendation.REQUEST_REP_CLARIFICATION,
        evidence=(),
        assessments=(),
        lines=(unmatched_line(MatchOutcome.NOT_ON_ORDER),),
        amount=None,
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == ()
    assert "asking the representative for clarification" in decision.explanation


def test_fr_1_14_a_recommendation_to_go_back_to_the_merchant_passes_through_untouched() -> None:
    decision = decide(Recommendation.REQUEST_INFO, evidence=(), assessments=(), amount=None)

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == ()


def test_fr_1_14_a_specific_non_evidence_detail_can_be_requested_from_the_merchant() -> None:
    decision = decide(
        Recommendation.REQUEST_INFO,
        amount=None,
        requested_details=("a clear photograph of the product label",),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == ()


def test_fr_1_14_an_unspecified_merchant_request_goes_back_to_the_representative() -> None:
    decision = decide(Recommendation.REQUEST_INFO, amount=None)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.MERCHANT_DETAILS_UNSPECIFIED,)


def test_fr_1_14_a_recommendation_to_hand_the_claim_to_a_person_passes_through_untouched() -> None:
    decision = decide(
        Recommendation.REQUEST_REP_CLARIFICATION, evidence=(), assessments=(), amount=None
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == ()


def test_fr_1_16_a_run_that_ran_out_of_steps_goes_to_a_person_however_clean_the_claim() -> None:
    decision = decide(Recommendation.APPROVE, budget_exhausted=True)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)
    assert "ran out of steps" in decision.explanation


def test_fr_1_16_what_the_investigation_established_is_carried_forward_not_thrown_away() -> None:
    decision = decide(Recommendation.APPROVE, budget_exhausted=True)

    assert decision.recommended_by_agent is Recommendation.APPROVE


def test_fr_1_16_running_out_of_steps_overrides_even_a_recommendation_to_refuse() -> None:
    decision = decide(Recommendation.REQUEST_REP_CLARIFICATION, budget_exhausted=True)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)


def test_fr_1_16_an_existing_rep_clarification_action_does_not_claim_a_change() -> None:
    decision = decide(Recommendation.REQUEST_REP_CLARIFICATION, budget_exhausted=True)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.BUDGET_EXHAUSTED,)
    assert "instead" not in decision.explanation
    assert "the same recommendation" in decision.explanation


def test_nfr_4_evidence_we_could_not_read_ourselves_goes_to_a_person() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.EVIDENCE_UNREADABLE in decision.overrides
    assert "could not read the damaged product photo" in decision.explanation


def test_fr_1_7_a_merchant_is_never_asked_for_something_only_we_could_fix() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert "the merchant" not in decision.explanation


def test_nfr_4_evidence_we_could_not_read_goes_to_a_person_even_after_a_refusal() -> None:
    decision = decide(
        Recommendation.REQUEST_REP_CLARIFICATION,
        evidence=evidence_with(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.UNREADABLE),
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.EVIDENCE_UNREADABLE,)


def test_fr_1_6_a_missing_photograph_sends_the_claim_back_to_the_merchant() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.MISSING),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    assert "damaged product photo" in decision.explanation


def test_fr_1_5_evidence_that_arrived_unusable_counts_as_not_having_it() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.UNUSABLE),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert "outer packaging photo" in decision.explanation


def test_fr_1_6_evidence_nobody_looked_for_is_not_evidence_we_have() -> None:
    decision = decide(Recommendation.APPROVE, evidence=())

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert decision.overrides == (OverrideReason.EVIDENCE_INCOMPLETE,)
    for kind in REQUIRED_EVIDENCE:
        assert kind.replace("_", " ") in decision.explanation


def test_fr_1_12_a_question_answered_no_asks_the_rep_for_clarification() -> None:
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
        assessment(AssessmentName.PRODUCT_ON_INVOICE),
        assessment(AssessmentName.PACKAGING_DOCUMENTED),
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.ASSESSMENT_FAILED,)
    assert "answered no on damage visible" in decision.explanation


def test_fr_1_12_a_question_that_was_never_answered_is_not_a_question_that_passed() -> None:
    answers = tuple(
        assessment(name)
        for name in AssessmentName
        if name is not AssessmentName.PACKAGING_DOCUMENTED
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.INVESTIGATION_INCOMPLETE,)
    assert "never answered packaging documented" in decision.explanation


def test_fr_1_12_a_failed_question_and_an_unanswered_one_are_both_reported() -> None:
    answers = (
        assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),
        assessment(AssessmentName.PRODUCT_IDENTIFIABLE),
    )

    decision = decide(Recommendation.APPROVE, assessments=answers)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert set(decision.overrides) == {
        OverrideReason.ASSESSMENT_FAILED,
        OverrideReason.INVESTIGATION_INCOMPLETE,
    }
    assert "answered no on damage visible" in decision.explanation
    assert "never answered product on invoice and packaging documented" in decision.explanation


def test_an_investigation_that_assessed_nothing_is_incomplete() -> None:
    decision = decide(Recommendation.APPROVE, assessments=())

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION

    assert decision.overrides == (OverrideReason.INVESTIGATION_INCOMPLETE,)


def test_fr_1_13_a_product_matching_two_order_lines_is_never_priced_by_choosing_one() -> None:
    decision = decide(
        Recommendation.APPROVE, lines=(unmatched_line(MatchOutcome.AMBIGUOUS),), amount=None
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "more than one line on the order" in decision.explanation


def test_fr_1a_2_a_product_that_is_not_on_the_order_cannot_be_reimbursed() -> None:
    decision = decide(
        Recommendation.APPROVE, lines=(unmatched_line(MatchOutcome.NOT_ON_ORDER),), amount=None
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "not on the order" in decision.explanation


def test_fr_1_21_an_approval_with_no_amount_worked_out_goes_to_a_person() -> None:
    decision = decide(Recommendation.APPROVE, amount=None)

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "no amount was worked out" in decision.explanation


def test_fr_1_18_an_approval_with_no_invoice_to_price_from_says_so() -> None:
    decision = decide(Recommendation.APPROVE, amount=amount_of_nothing(priced_from=None))

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (OverrideReason.PRODUCT_NOT_PRICEABLE,)
    assert "no invoice to price it from" in decision.explanation


def test_fr_1_18_an_approval_whose_product_was_not_on_the_invoice_names_the_invoice() -> None:
    decision = decide(Recommendation.APPROVE, amount=amount_of_nothing(priced_from="INV-342578703"))

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert "nothing could be priced from invoice INV-342578703" in decision.explanation


def test_fr_1_20_an_item_the_invoice_prices_at_nothing_goes_to_a_person() -> None:
    free_item = AmountComponent(
        product_name="Insert Card",
        quantity=1,
        unit_price=Decimal("0.00"),
        sku="Insert",
    )

    decision = decide(
        Recommendation.APPROVE,
        amount=amount_of_nothing(priced_from="INV-342578703", components=(free_item,)),
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert "prices the damaged goods at nothing" in decision.explanation


def test_nfr_4_the_most_cautious_recommendation_wins_when_two_rules_disagree() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.MISSING),
        lines=(unmatched_line(MatchOutcome.AMBIGUOUS),),
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.PRODUCT_NOT_PRICEABLE,
    )


def test_nfr_3_every_rule_that_stepped_in_is_reported_and_not_only_the_first() -> None:
    evidence = (
        finding(EvidenceKind.INVOICE, EvidenceState.MISSING),
        finding(EvidenceKind.CUSTOMER_CONFIRMATION, EvidenceState.UNREADABLE),
    )
    answers = (assessment(AssessmentName.DAMAGE_VISIBLE, passed=False),)

    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence,
        assessments=answers,
        lines=(unmatched_line(MatchOutcome.NOT_ON_ORDER),),
        amount=None,
        budget_exhausted=True,
    )

    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert decision.overrides == (
        OverrideReason.BUDGET_EXHAUSTED,
        OverrideReason.EVIDENCE_UNREADABLE,
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.ASSESSMENT_FAILED,
        OverrideReason.INVESTIGATION_INCOMPLETE,
        OverrideReason.PRODUCT_NOT_PRICEABLE,
    )


def test_nfr_3_merchant_gaps_and_wrong_assessments_remain_distinct() -> None:
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

    assert decision.overrides == (
        OverrideReason.EVIDENCE_INCOMPLETE,
        OverrideReason.ASSESSMENT_FAILED,
    )
    assert decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert "the merchant has still to supply the invoice" in decision.explanation
    assert "answered no on damage visible" in decision.explanation


def test_nfr_1_the_same_claim_line_always_reaches_the_same_decision() -> None:
    first = decide(Recommendation.APPROVE, evidence=(), assessments=(), amount=None)
    second = decide(Recommendation.APPROVE, evidence=(), assessments=(), amount=None)

    assert first == second


def test_nfr_4_a_shortcoming_of_ours_never_sends_a_request_to_the_merchant() -> None:
    ours_to_fix = {
        OverrideReason.EVIDENCE_UNREADABLE,
        OverrideReason.INVESTIGATION_INCOMPLETE,
        OverrideReason.BUDGET_EXHAUSTED,
    }

    for reason in ours_to_fix:
        assert _WITHHELD_RECOMMENDATION[reason] is not Recommendation.REQUEST_INFO

    asks_the_merchant = {
        reason
        for reason, outcome in _WITHHELD_RECOMMENDATION.items()
        if outcome is Recommendation.REQUEST_INFO
    }
    assert asks_the_merchant == {OverrideReason.EVIDENCE_INCOMPLETE}


def expensive_goods(items_total: str, *, paid: str = "100.00") -> AmountDerivation:
    return AmountDerivation(
        components=(
            AmountComponent(
                product_name=COLLAGEN,
                quantity=1,
                unit_price=Decimal(items_total),
                sku="COLLAGEN1",
            ),
        ),
        items_total_usd=Decimal(items_total),
        proposed_usd=Decimal(items_total),
        amount_usd=Decimal(paid),
        cap_usd=Decimal("100.00"),
        cap_applied=Decimal(items_total) > Decimal("100.00"),
        priced_from="INV-342578703",
    )


def test_fr_c_7_an_approval_of_expensive_goods_asks_for_a_second_look() -> None:
    decision = decide(Recommendation.APPROVE, amount=expensive_goods("600.00"))

    assert decision.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert decision.recommended_by_agent is Recommendation.APPROVE
    assert "$600.00" in decision.explanation
    assert "$500.00" in decision.explanation
    assert "second look" in decision.explanation


def test_fr_c_7_the_label_withholds_nothing_and_reports_no_rule_as_having_stepped_in() -> None:
    decision = decide(Recommendation.APPROVE, amount=expensive_goods("600.00"))

    assert decision.recommendation.is_approval
    assert decision.overrides == ()
    assert not decision.was_overridden
    assert decision.waived == ()


def test_fr_c_7_goods_under_the_figure_are_approved_without_a_label() -> None:
    decision = decide(Recommendation.APPROVE, amount=expensive_goods("52.00", paid="52.00"))

    assert decision.recommendation is Recommendation.APPROVE
    assert "high value" not in decision.explanation


def test_fr_c_7_what_the_goods_cost_is_compared_and_not_what_would_be_paid() -> None:
    decision = decide(Recommendation.APPROVE, amount=expensive_goods("600.00"))

    assert decision.recommendation is Recommendation.APPROVE_HIGH_VALUE

    assert expensive_goods("600.00").amount_usd == Decimal("100.00")


def test_fr_c_7_the_figure_comes_from_the_claim_policy() -> None:
    decision = decide(
        Recommendation.APPROVE,
        amount=expensive_goods("52.00", paid="52.00"),
        policy=Policy(high_value_order_usd=Decimal("40.00")),
    )

    assert decision.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert "$40.00" in decision.explanation


def test_fr_c_7_goods_landing_exactly_on_the_figure_follow_the_same_setting_as_an_order() -> None:
    at_the_figure = expensive_goods("500.00")

    inclusive = decide(Recommendation.APPROVE, amount=at_the_figure, policy=Policy())
    exclusive = decide(
        Recommendation.APPROVE,
        amount=at_the_figure,
        policy=Policy(high_value_inclusive=False),
    )

    assert inclusive.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert exclusive.recommendation is Recommendation.APPROVE


def test_fr_c_7_a_claim_the_rules_withheld_is_never_labelled_instead() -> None:
    decision = decide(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.MISSING),
        amount=expensive_goods("600.00"),
    )

    assert decision.recommendation is Recommendation.REQUEST_INFO
    assert OverrideReason.EVIDENCE_INCOMPLETE in decision.overrides


def test_fr_c_7_a_payment_a_representative_directed_is_labelled_too() -> None:
    decision = decide_outcome(
        Recommendation.APPROVE,
        evidence=evidence_with(EvidenceKind.INVOICE, EvidenceState.MISSING),
        assessments=all_questions_answered(),
        lines=(matched_line(),),
        amount=expensive_goods("600.00"),
        policy=Policy(),
        directed_by_representative=True,
    )

    assert decision.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert decision.directed_by_representative
    assert OverrideReason.EVIDENCE_INCOMPLETE in decision.waived


def test_fr_c_7_only_an_approval_is_ever_labelled() -> None:
    for recommended in (Recommendation.REQUEST_INFO, Recommendation.REQUEST_REP_CLARIFICATION):
        decision = decide(
            recommended,
            amount=expensive_goods("600.00"),
            requested_details=("A photograph of the outer box.",),
        )

        assert decision.recommendation is recommended


def test_fr_1_14_both_ways_of_recommending_a_payment_answer_to_the_same_question() -> None:
    approvals = {outcome for outcome in Recommendation if outcome.is_approval}

    assert approvals == {Recommendation.APPROVE, Recommendation.APPROVE_HIGH_VALUE}
