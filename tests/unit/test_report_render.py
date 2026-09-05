"""Writing what was established into the report a representative reads (FR-2.1 to FR-2.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tests.fixtures.shipbob import CASE_1001, ORDER_1001

from claim_agent.agent.budget import BudgetSnapshot
from claim_agent.agent.investigate import LineInvestigation
from claim_agent.domain.assessment import Assessment, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, build_claim_lines
from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.models import (
    Case,
    DraftedEmail,
    GateName,
    MerchantCorrection,
    Order,
    TerminalReason,
)
from claim_agent.domain.outcome import OutcomeDecision, OverrideReason, Recommendation
from claim_agent.domain.reimbursement import AmountComponent, AmountDerivation
from claim_agent.preflight.models import ClaimContext, GateResult, TerminalReport
from claim_agent.report.models import EmailWording
from claim_agent.report.render import (
    render_investigated_product,
    render_stopped_claim,
    render_what_the_representative_decided,
)

CASE = Case.model_validate(CASE_1001)
ORDER = Order.model_validate(ORDER_1001)
COLLAGEN = "Liposomal Tripeptide Collagen"
A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)


def a_context(**overrides: Any) -> ClaimContext:
    """The facts worked out before the AI ran, so a test writes only the part it is about."""
    fields: dict[str, Any] = {
        "order_value_usd": Decimal("208.00"),
        "is_high_value": False,
        "days_since_delivery": 4,
        "delivered_date": A_MOMENT,
        "merchant_corrections": (),
    }
    fields.update(overrides)
    return ClaimContext(**fields)


def an_amount(**overrides: Any) -> AmountDerivation:
    """The working behind a figure, priced from an invoice."""
    fields: dict[str, Any] = {
        "components": (
            AmountComponent(
                product_name=COLLAGEN, sku="COLLAGEN1", quantity=1, unit_price=Decimal("52.00")
            ),
        ),
        "items_total_usd": Decimal("52.00"),
        "proposed_usd": Decimal("52.00"),
        "amount_usd": Decimal("52.00"),
        "cap_usd": Decimal("100.00"),
        "cap_applied": False,
        "reasoning": "The bottle is smashed, so the whole item is a loss.",
        "priced_from": "INV-342578703",
    }
    fields.update(overrides)
    return AmountDerivation(**fields)


def all_four_evidence() -> tuple[EvidenceFinding, ...]:
    """Every piece of evidence found, each naming the image it came from."""
    return (
        EvidenceFinding(
            kind=EvidenceKind.INVOICE,
            state=EvidenceState.PRESENT,
            observed="An invoice listing the collagen at $52.00.",
            attachment_id="ATT-CASE-1001-02",
        ),
        EvidenceFinding(
            kind=EvidenceKind.CUSTOMER_CONFIRMATION,
            state=EvidenceState.PRESENT,
            observed="An email from the customer saying the bottle arrived broken.",
            attachment_id="ATT-CASE-1001-01",
        ),
        EvidenceFinding(
            kind=EvidenceKind.DAMAGED_PRODUCT_PHOTO,
            state=EvidenceState.PRESENT,
            observed="The collagen bottle, cracked down one side.",
            attachment_id="ATT-CASE-1001-03",
        ),
        EvidenceFinding(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
            state=EvidenceState.MISSING,
            observed="No photograph of the outer mailer was supplied.",
        ),
    )


def a_line(**overrides: Any) -> LineInvestigation:
    """A finished investigation of one damaged product."""
    line = build_claim_lines(
        "CASE-1001", [ClaimedProduct(name=COLLAGEN, sku="COLLAGEN1", quantity=1)], ORDER
    )[0]
    fields: dict[str, Any] = {
        "line": line,
        "evidence": all_four_evidence(),
        "assessments": (
            Assessment(
                name=AssessmentName.DAMAGE_VISIBLE,
                passed=True,
                reasoning="The crack runs the length of the bottle.",
                confidence=0.95,
                attachment_ids=("ATT-CASE-1001-03",),
            ),
        ),
        "outcome": OutcomeDecision(
            recommendation=Recommendation.APPROVE,
            recommended_by_agent=Recommendation.APPROVE,
            explanation="The investigation recommends paying this line.",
        ),
        "amount": an_amount(),
        "concerns": ("The outer packaging photograph is missing.",),
        "drafted_email": DraftedEmail(
            to="merchant@example.test",
            subject="About your claim",
            body="We will refund $52.00 for the damaged collagen.",
        ),
        "ledger": (),
        "budget": BudgetSnapshot(
            steps_used=2,
            steps_allowed=12,
            image_analyses_used=1,
            image_analyses_allowed=20,
            tool_retries_used=0,
            tool_retries_allowed_per_call=2,
            limits_reached=(),
        ),
        "conclusion": None,
    }
    fields.update(overrides)
    return LineInvestigation(**fields)


def a_stopped_claim(**overrides: Any) -> TerminalReport:
    """A claim the quick checks turned away for being too old."""
    fields: dict[str, Any] = {
        "case_id": "CASE-1004",
        "account_name": "Catalyze-X",
        "user_id": "374167",
        "reasons": (TerminalReason.CLAIM_TOO_OLD,),
        "findings": ("The claim was filed 73 days after delivery, past the 60 day limit.",),
        "gates": (
            GateResult(
                gate=GateName.AGE,
                passed=False,
                reason=TerminalReason.CLAIM_TOO_OLD,
                explanation="Filed 73 days after delivery, past the 60 day limit.",
                observed={"days_since_delivery": "73", "age_limit_days": "60"},
            ),
            GateResult(
                gate=GateName.INSURANCE,
                passed=True,
                explanation="The parcel was not insured.",
                observed={"is_insured": "False"},
            ),
        ),
        "context": a_context(days_since_delivery=73),
        "drafted_email": DraftedEmail(
            to="merchant@example.test",
            subject="About your claim",
            body="This claim was filed more than 60 days after delivery.",
        ),
        "requires_escalation": False,
    }
    fields.update(overrides)
    return TerminalReport(**fields)


def rendered(**overrides: Any) -> str:
    """One investigated product's report as markdown."""
    return render_investigated_product(line=a_line(**overrides), context=a_context(), case=CASE)


# --- Every section a representative needs is there (FR-2.1 to FR-2.7) --------


def test_every_required_section_appears() -> None:
    """FR-2.1 to FR-2.7: a report the rep has to leave to check is a report that failed."""
    document = rendered()

    for heading in (
        "## Recommendation",
        "## Concerns",
        "## The claim in context",
        "## The evidence",
        "## The four questions",
        "## How the amount was reached",
        "## The merchant's email",
    ):
        assert heading in document


def test_the_recommendation_and_the_amount_lead_the_report() -> None:
    """FR-2.5a: a rep who agrees should be able to approve without going looking."""
    document = rendered()

    assert document.index("## Recommendation") < document.index("## The evidence")
    assert document.index("## Concerns") < document.index("## The evidence")
    assert "**Amount recommended: $52.00.**" in document


def test_the_report_says_it_is_a_recommendation_rather_than_a_result() -> None:
    """FR-2.1, FR-1.17: nothing has happened, and the wording must not suggest it has."""
    document = rendered()

    assert "This is a recommendation. Nothing is sent and nothing is paid until you approve" in (
        document
    )


# --- Evidence is traceable to the image it came from (FR-2.2) ----------------


def test_each_piece_of_evidence_names_the_image_it_came_from() -> None:
    """FR-2.2: a rep must be able to open the very photograph the system looked at."""
    document = rendered()

    assert "`ATT-CASE-1001-02`" in document
    assert "`ATT-CASE-1001-03`" in document


def test_evidence_nobody_found_is_written_down_rather_than_left_out() -> None:
    """FR-2.2: all four are shown, so a gap is seen rather than inferred from silence."""
    document = rendered()

    assert "outer packaging photo" in document
    assert "missing" in document


# --- The four questions, and the ones nobody answered (FR-2.3) ---------------


def test_an_assessment_carries_its_reasoning_and_how_sure_it_was() -> None:
    """FR-2.3: a rep has to be able to disagree with one answer without discarding the rest."""
    document = rendered()

    assert "damage visible" in document
    assert "The crack runs the length of the bottle." in document
    assert "0.95" in document


def test_questions_nobody_answered_are_said_to_be_unanswered() -> None:
    """FR-2.3: never answered and answered no are different, and must never read alike."""
    document = rendered()

    assert "never answered, which is not the same as being answered no" in document


def test_an_investigation_that_answered_nothing_says_so() -> None:
    """FR-2.3: three missing rows and no note would leave a reader guessing which it was."""
    document = rendered(assessments=())

    assert "None of the four questions was answered." in document


# --- Concerns are never silent (FR-2.5) --------------------------------------


def test_a_concern_the_investigation_raised_is_shown() -> None:
    """FR-2.5: a rep who cannot tell why the system is unsure will rubber-stamp or redo it."""
    assert "The outer packaging photograph is missing." in rendered()


def test_a_report_with_nothing_worrying_says_so_rather_than_showing_a_blank() -> None:
    """FR-2.5: silence here is a defect, so an empty list is written out in words."""
    document = rendered(concerns=())

    assert "Nothing was flagged as weak, conflicting or uncertain." in document


# --- How the amount was reached (FR-2.4) -------------------------------------


def test_the_working_behind_the_figure_is_shown() -> None:
    """FR-2.4: "$52.00" alone is not reviewable."""
    document = rendered()

    assert "$52.00" in document
    assert COLLAGEN in document
    assert "`INV-342578703`" in document
    assert "That limit did not change the answer." in document


def test_the_cap_changing_the_answer_is_said_plainly() -> None:
    """FR-1.20, FR-2.4: a rep must be able to see the limit was what produced the figure."""
    document = rendered(
        amount=an_amount(
            proposed_usd=Decimal("150.00"), amount_usd=Decimal("100.00"), cap_applied=True
        )
    )

    assert "That limit changed the answer." in document


def test_a_product_that_could_not_be_priced_says_why() -> None:
    """FR-2.4, FR-1.18: a rep can chase a missing invoice; they cannot chase silence."""
    document = rendered(
        amount=an_amount(
            components=(),
            items_total_usd=Decimal("0.00"),
            amount_usd=Decimal("0.00"),
            priced_from=None,
        )
    )

    assert "No item on the order could be priced for this product." in document
    assert "There was no invoice to price it from." in document


def test_a_figure_is_written_from_an_exact_decimal_rather_than_a_float() -> None:
    """FR-1.21: cents drift through a float, and a drifted figure is one nobody can trust."""
    document = rendered(
        amount=an_amount(
            components=(
                AmountComponent(
                    product_name=COLLAGEN,
                    sku="COLLAGEN1",
                    quantity=3,
                    unit_price=Decimal("0.10"),
                ),
            ),
            items_total_usd=Decimal("0.30"),
            proposed_usd=Decimal("0.30"),
            amount_usd=Decimal("0.30"),
        )
    )

    # Three tenths is the classic figure a float cannot hold: 0.1 * 3 is 0.30000000000000004.
    assert "$0.30" in document
    assert "0.30000" not in document


# --- A rule that stepped in is visible (NFR-3) -------------------------------


def test_a_rule_that_withheld_a_payment_is_named() -> None:
    """NFR-3: a rep should see the rules disagreed, not only the outcome they produced."""
    document = rendered(
        outcome=OutcomeDecision(
            recommendation=Recommendation.REQUEST_INFO,
            recommended_by_agent=Recommendation.APPROVE,
            overrides=(OverrideReason.EVIDENCE_INCOMPLETE,),
            explanation="The merchant has still to supply the outer packaging photo.",
        )
    )

    assert "evidence incomplete" in document
    assert "`approve`" in document


# --- The merchant's email, exactly as it would be sent (FR-2.7) --------------


def test_the_email_is_shown_in_the_exact_wording_that_would_be_sent() -> None:
    """FR-2.7: a rep approves wording, so the wording has to be the wording."""
    document = rendered()

    assert "Subject: About your claim" in document
    assert "We will refund $52.00 for the damaged collagen." in document


def test_the_email_is_fenced_so_nothing_reinterprets_it() -> None:
    """FR-2.7: a character in a merchant's email must not become formatting in a report."""
    document = rendered(
        drafted_email=DraftedEmail(
            to="merchant@example.test",
            subject="About your claim",
            body="# Not a heading, and *not* emphasis.",
        )
    )

    assert "```text" in document
    assert "# Not a heading, and *not* emphasis." in document


def test_the_report_marks_the_draft_without_the_email_saying_so_itself() -> None:
    """FR-1.17: the word draft must never be able to reach a merchant."""
    document = rendered()

    assert "This is a draft." in document
    assert "draft" not in a_line().drafted_email.body.lower()  # type: ignore[union-attr]


def test_a_claim_with_no_email_says_what_that_means() -> None:
    """NFR-4: a missing email is something a rep must know before approving, not discover."""
    document = rendered(drafted_email=None)

    assert "There is none." in document


def test_an_email_with_nowhere_to_go_is_flagged() -> None:
    """FR-3.2: the recipient comes from the claim, and a claim without one cannot be answered."""
    document = rendered(
        drafted_email=DraftedEmail(to=None, subject="About your claim", body="Hello.")
    )

    assert "no address on the claim" in document


# --- What the merchant was corrected about before (FR-2.6) -------------------


def test_a_merchant_with_no_history_is_said_to_have_none() -> None:
    """FR-2.6: a merchant new to us and one never corrected read alike, and both matter."""
    document = rendered()

    assert "none on file" in document


def test_a_past_correction_that_changed_the_conclusion_is_marked() -> None:
    """FR-2.6: a rep is owed which past correction influenced this recommendation."""
    line = a_line()
    document = render_investigated_product(
        line=line,
        context=a_context(
            merchant_corrections=(
                MerchantCorrection(
                    user_id="334430",
                    case_id="CASE-0900",
                    summary="The two-pack was claimed, not the single bottle.",
                    recorded_at=A_MOMENT,
                ),
            )
        ),
        case=CASE,
    )

    assert "CASE-0900" in document
    assert "The two-pack was claimed, not the single bottle." in document


def test_a_high_value_order_is_called_out() -> None:
    """FR-2.6: whether this warrants more care is something a rep decides knowing it."""
    document = render_investigated_product(
        line=a_line(),
        context=a_context(order_value_usd=Decimal("620.00"), is_high_value=True),
        case=CASE,
    )

    assert "$620.00" in document
    assert "high-value order" in document


def test_an_order_that_could_not_be_read_is_not_reported_as_worth_nothing() -> None:
    """FR-0.5: missing is not the same as empty, and a rep must be able to tell."""
    document = render_investigated_product(
        line=a_line(), context=a_context(order_value_usd=None), case=CASE
    )

    assert "could not be read" in document


# --- A claim the quick checks stopped (FR-0.4, FR-2.5) -----------------------


def test_a_stopped_claim_reports_every_reason_and_all_four_checks() -> None:
    """FR-0.3, FR-0.4: a rep sees what passed rather than inferring it from silence."""
    document = render_stopped_claim(a_stopped_claim(), case=CASE)

    assert "## Why this claim was stopped" in document
    assert "claim too old" in document
    assert "## The four checks" in document
    assert "The parcel was not insured." in document


def test_a_stopped_claims_findings_become_its_concerns() -> None:
    """FR-2.5: a report with an empty concerns section would be reporting a clean result."""
    document = render_stopped_claim(a_stopped_claim(), case=CASE)

    assert "## Concerns" in document
    assert "past the 60 day limit" in document


def test_an_insured_claim_says_it_is_routed_out_and_carries_no_email() -> None:
    """FR-0.2, FR-0.4: no email explains insurance, so none is written."""
    document = render_stopped_claim(
        a_stopped_claim(
            reasons=(TerminalReason.SHIPMENT_INSURED,),
            findings=("The parcel was insured.",),
            drafted_email=None,
            requires_escalation=True,
        ),
        case=CASE,
    )

    assert "routed out rather than answered" in document
    assert "no email explains that to a merchant" in document


# --- What the representative then decided (FR-2.8, FR-C.1) -------------------


def test_an_approval_that_changed_nothing_says_so() -> None:
    """FR-C.1: the record has to say what a person chose, including choosing nothing new."""
    advised = Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00"))
    section = render_what_the_representative_decided(
        review_number=1,
        action=RepAction.APPROVED,
        recommended=advised,
        decided=advised,
        edited_email=None,
        rep_words=None,
        over_the_cap_by=None,
    )

    assert section.startswith("## Review 1 — what the representative decided")
    assert "approved this report as it stood" in section
    assert "Amount changed" not in section


def test_an_override_names_both_figures() -> None:
    """FR-2.1: a report approved at a different figure must not show only the old one."""
    section = render_what_the_representative_decided(
        review_number=1,
        action=RepAction.APPROVED_WITH_OVERRIDE,
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00")),
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
        edited_email=EmailWording(
            subject="About your claim",
            body="We will refund $31.20 for the damaged collagen.",
        ),
        rep_words="Customer confirmation came in by phone.",
        over_the_cap_by=None,
    )

    assert "$52.00" in section
    assert "$31.20" in section
    assert "reworded" in section
    assert "We will refund $31.20 for the damaged collagen." in section
    assert "Customer confirmation came in by phone." in section


def test_a_figure_over_the_limit_is_recorded_and_flagged_rather_than_refused() -> None:
    """FR-1.20, FR-R.8: the limit is on what the system recommends, not on what a person may do."""
    section = render_what_the_representative_decided(
        review_number=1,
        action=RepAction.APPROVED_WITH_OVERRIDE,
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00")),
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("150.00")),
        edited_email=None,
        rep_words=None,
        over_the_cap_by=Decimal("50.00"),
    )

    assert "$150.00" in section
    assert "$50.00 over the most the system may recommend" in section


# --- Writing values out safely -----------------------------------------------


def test_a_bar_in_a_sentence_cannot_break_the_table_around_it() -> None:
    """NFR-3: a finding that shifts every column after it is a finding nobody can read."""
    document = rendered(
        evidence=(
            EvidenceFinding(
                kind=EvidenceKind.INVOICE,
                state=EvidenceState.PRESENT,
                observed="Two columns | one row.",
                attachment_id="ATT-CASE-1001-02",
            ),
        )
    )

    assert "Two columns \\| one row." in document


def test_the_same_findings_are_written_the_same_way_twice() -> None:
    """NFR-1: a report that changes when nothing changed is a report nobody can rely on."""
    assert rendered() == rendered()
