from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.test_report_render import a_context, a_line, a_stopped_claim

from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.decision import DecisionStage, Proposal
from claim_agent.domain.models import DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.report.models import (
    ClaimView,
    InvestigationReportContent,
    Report,
    ReportState,
    RevisionTurn,
    ScreeningReportContent,
)

A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)


def a_report(**overrides: Any) -> Report:
    """One investigated claim's report, so a test writes down only the part it is about."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1001",
        "version": 1,
        "case_id": "CASE-1001",
        "product_names": ("Liposomal Tripeptide Collagen",),
        "account_name": "Best Paw Nutrition",
        "user_id": "334430",
        "stage": DecisionStage.INVESTIGATION,
        "state": ReportState.AWAITING_REVIEW,
        "recommendation": Recommendation.APPROVE,
        "amount_usd": Decimal("52.00"),
        "confidence": 0.9,
        "carrier": "UPS",
        "defect_type": None,
        "damage_type": None,
        "order_value_usd": Decimal("208.00"),
        "decided": None,
        "decisions_taken": 0,
        "drafted_email": DraftedEmail(
            to="merchant@example.test", subject="About your claim", body="Hello."
        ),
        "created_at": A_MOMENT,
    }
    fields.update(overrides)
    if "content" not in fields:
        findings = a_line()
        fields["content"] = InvestigationReportContent(
            lines=tuple(
                _named(findings.lines[0], name, position)
                for position, name in enumerate(fields["product_names"], start=1)
            ),
            context=a_context(),
            evidence=findings.evidence,
            assessments=findings.assessments,
            outcome=findings.outcome.model_copy(
                update={"recommendation": fields["recommendation"]}
            ),
            amount=findings.amount.model_copy(update={"amount_usd": fields["amount_usd"]}),
            concerns=findings.concerns,
            requested_details=(
                ("a clear photograph showing the full product label",)
                if fields["recommendation"] is Recommendation.REQUEST_INFO
                else ()
            ),
        )
    return Report(**fields)


def _named(line: ClaimLine, name: str, position: int) -> ClaimLine:
    """The same claim line under a given product name, so a test can ask for several."""
    return line.model_copy(
        update={
            "claim_line_id": f"CASE-1001-L{position:02d}",
            "claimed": line.claimed.model_copy(update={"name": name}),
            "order_line": (
                line.order_line.model_copy(update={"name": name})
                if line.order_line is not None
                else None
            ),
        }
    )


def a_screening_report(**overrides: Any) -> Report:
    """A claim the quick checks turned away, which has no damaged product in it."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1004",
        "case_id": "CASE-1004",
        "product_names": (),
        "stage": DecisionStage.SCREENING,
        "recommendation": None,
        "amount_usd": None,
        "confidence": None,
        "content": ScreeningReportContent(
            context=a_context(days_since_delivery=73),
            reasons=a_stopped_claim().reasons,
            findings=a_stopped_claim().findings,
            gates=a_stopped_claim().gates,
            requires_rep_clarification=a_stopped_claim().requires_rep_clarification,
        ),
    }
    fields.update(overrides)
    return a_report(**fields)


def test_fr_c_7_a_high_value_approval_is_a_report_that_carries_an_amount_and_an_email() -> None:
    """FR-C.7 with FR-1.14: labelled or not, an approval is an approval.

    The rules a report is held to know both ways of recommending a payment. If they knew
    only the plain one, a labelled approval would be a report the checks read as carrying
    money it should not have and an email it should not need — and it would be refused for
    being exactly what it is.
    """
    report = a_report(recommendation=Recommendation.APPROVE_HIGH_VALUE)

    assert report.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert report.amount_usd == Decimal("52.00")
    assert report.drafted_email is not None


def test_fr_c_7_a_high_value_approval_without_its_email_is_refused() -> None:
    """FR-1.14: a merchant-facing action with nothing to send is a report nobody can act on."""
    with pytest.raises(ValidationError):
        a_report(recommendation=Recommendation.APPROVE_HIGH_VALUE, drafted_email=None)


# --- A stopped claim names a whole claim, not a product (FR-C.1) --------------


def test_a_stopped_claim_names_no_damaged_product() -> None:
    """FR-C.1: the split into products happens later, so a stopped claim never has one."""
    report = a_screening_report()

    assert report.product_names == ()
    assert report.stage is DecisionStage.SCREENING


def test_a_stopped_claim_carrying_a_product_is_refused() -> None:
    """FR-C.1: a product on a claim that never reached the split is a mistake in our own code."""
    with pytest.raises(ValidationError):
        a_screening_report(product_names=("Liposomal Tripeptide Collagen",))


def test_an_investigated_report_has_to_name_what_was_damaged() -> None:
    """FR-2.9a: a report that names no product cannot be told apart from a clarification."""
    with pytest.raises(ValidationError):
        a_report(product_names=())


# --- A stopped claim recommends nothing (FR-2.1) ------------------------------


def test_a_stopped_claim_recommends_nothing_and_that_is_a_real_answer() -> None:
    """FR-2.1: the three actions are about a damaged product, and there is none."""
    report = a_screening_report()

    assert report.recommendation is None
    assert report.amount_usd is None


@pytest.mark.parametrize(
    "invented",
    [
        {"recommendation": Recommendation.REQUEST_REP_CLARIFICATION},
        {"amount_usd": Decimal("52.00")},
    ],
)
def test_a_stopped_claim_given_a_recommendation_is_refused(invented: dict[str, Any]) -> None:
    """FR-2.1: turning a claim's reasons into a recommendation would invent an answer."""
    with pytest.raises(ValidationError):
        a_screening_report(**invented)


def test_a_screening_clarification_request_cannot_carry_an_email() -> None:
    """The representative-facing screening action must not generate merchant wording."""
    stopped = a_stopped_claim()
    content = ScreeningReportContent(
        context=a_context(days_since_delivery=73),
        reasons=stopped.reasons,
        findings=stopped.findings,
        gates=stopped.gates,
        requires_rep_clarification=True,
    )

    with pytest.raises(ValidationError, match="must not carry an email"):
        a_screening_report(content=content)


def test_a_merchant_facing_screening_report_needs_an_email() -> None:
    """A merchant-facing next action returns the second output as an email draft."""
    with pytest.raises(ValidationError, match="needs an email draft"):
        a_screening_report(drafted_email=None)


# --- The action controls whether the second output exists --------------------


@pytest.mark.parametrize("recommendation", [Recommendation.APPROVE, Recommendation.REQUEST_INFO])
def test_a_merchant_facing_investigation_action_needs_an_email(
    recommendation: Recommendation,
) -> None:
    """Approval and merchant-information actions always return an email draft."""
    amount = Decimal("52.00") if recommendation is Recommendation.APPROVE else None

    with pytest.raises(ValidationError, match="needs an email draft"):
        a_report(recommendation=recommendation, amount_usd=amount, drafted_email=None)


def test_a_rep_clarification_action_cannot_carry_an_email() -> None:
    """Ambiguous or incorrect claims stay with the representative and generate no email."""
    with pytest.raises(ValidationError, match="must not carry an email"):
        a_report(
            recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
            amount_usd=None,
        )


def test_a_merchant_information_report_must_name_the_details_needed() -> None:
    """The claim report is actionable without making the rep infer from the email."""
    report = a_report(recommendation=Recommendation.REQUEST_INFO, amount_usd=None)
    assert isinstance(report.content, InvestigationReportContent)
    content = report.content.model_copy(update={"requested_details": ()})

    with pytest.raises(ValidationError, match="specific details needed"):
        a_report(
            recommendation=Recommendation.REQUEST_INFO,
            amount_usd=None,
            content=content,
        )


# --- What the representative settled on (FR-2.1) ------------------------------


def test_what_the_representative_settled_on_is_kept_beside_what_was_advised() -> None:
    """FR-2.1: a report approved at a different figure must not show the old one."""
    report = a_report(
        state=ReportState.APPROVED,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    assert report.amount_usd == Decimal("52.00")
    assert report.decided is not None
    assert report.decided.amount_usd == Decimal("31.20")


def test_a_figure_on_a_report_nobody_approved_is_refused() -> None:
    """FR-2.9: what a representative settled on only exists once they have settled on it."""
    with pytest.raises(ValidationError):
        a_report(decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")))


# --- Counting upwards (FR-R.13, FR-C.1) ---------------------------------------


@pytest.mark.parametrize("impossible", [{"version": 0}, {"decisions_taken": -1}])
def test_a_count_below_its_floor_is_refused(impossible: dict[str, Any]) -> None:
    """FR-R.13, FR-C.1: neither is reachable by counting upwards from a report being written."""
    with pytest.raises(ValidationError):
        a_report(**impossible)


# --- A report is the account of something that already happened ---------------


def test_a_report_cannot_be_edited_in_place() -> None:
    """NFR-5: a report is a record, so moving its review on makes a copy rather than an edit."""
    report = a_report()

    with pytest.raises(ValidationError):
        report.state = ReportState.APPROVED  # type: ignore[misc]

    moved_on = report.model_copy(update={"state": ReportState.APPROVED})
    assert report.state is ReportState.AWAITING_REVIEW
    assert moved_on.state is ReportState.APPROVED


def test_a_field_nobody_declared_is_refused() -> None:
    """NFR-2: a report is written and read back, so a stray field is a fault rather than noise."""
    with pytest.raises(ValidationError):
        a_report(recommended_amount="52.00")


def test_a_report_survives_being_written_down_and_read_back() -> None:
    """FR-R.13: what is kept has to come back as the very same report."""
    report = a_report(
        state=ReportState.APPROVED,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    read_back = Report.model_validate_json(report.model_dump_json())

    assert read_back == report


def test_money_is_written_down_as_text_rather_than_a_number() -> None:
    """FR-1.21: a figure that went through a floating point number is a figure we cannot trust."""
    written = a_report().model_dump(mode="json")

    assert written["amount_usd"] == "52.00"


def test_a_report_is_structured_and_does_not_carry_a_second_prose_document() -> None:
    """FR-2.10: the UI receives report data once and owns how it is presented."""
    written = a_report().model_dump(mode="json")

    assert written["content"]["kind"] == "investigation"
    assert "markdown" not in written


# --- The claim view (FR-2.9b) -------------------------------------------------


def test_a_claim_nobody_has_asked_about_has_no_reports_and_that_is_ordinary() -> None:
    """FR-2.9b: an empty list is a claim nobody investigated, not a store that failed."""
    view = ClaimView(case_id="CASE-1001")

    assert view.reports == ()


def test_fr_2_9a_one_report_names_every_damaged_product_on_the_claim() -> None:
    """FR-2.9a: a representative deciding sees the whole claim rather than inferring it."""
    report = a_report(product_names=("Liposomal Tripeptide Collagen", "Blue Razz Liquid Carnitine"))

    assert report.product_names == (
        "Liposomal Tripeptide Collagen",
        "Blue Razz Liquid Carnitine",
    )


# --- The conversation on a report (FR-R.13) -----------------------------------


def a_turn(**overrides: Any) -> RevisionTurn:
    """One round of a representative and the agent talking about a report."""
    fields: dict[str, Any] = {
        "turn": 1,
        "from_version": 1,
        "feedback": "The packaging photo is the box, not the product.",
        "reply": "You were right; I have marked it missing.",
        "changed": ("Marked the outer packaging photograph missing.",),
    }
    fields.update(overrides)
    return RevisionTurn(**fields)


def test_a_report_that_has_never_been_sent_back_carries_no_conversation() -> None:
    """FR-R.13: an empty conversation is the ordinary case, not a missing record."""
    assert a_report().revisions == ()


def test_the_rounds_of_a_conversation_have_to_be_numbered_in_order() -> None:
    """FR-R.13: a record of how a decision was reached has to be readable in sequence."""
    with pytest.raises(ValidationError, match="numbered in order"):
        a_report(version=3, revisions=(a_turn(), a_turn(turn=3, from_version=2)))


def test_a_round_cannot_answer_a_version_that_did_not_exist_yet() -> None:
    """FR-R.13: a note is written on a version the representative was actually looking at."""
    with pytest.raises(ValidationError, match="this version"):
        a_report(version=2, revisions=(a_turn(from_version=3),))


def test_a_question_only_round_can_be_recorded_on_the_current_version() -> None:
    """A conversation does not create a report version when none of its findings changed."""
    report = a_report(version=1, revisions=(a_turn(from_version=1, reworked=False),))

    assert report.revisions[0].from_version == report.version


def test_a_round_says_whether_the_report_was_actually_reworked() -> None:
    """NFR-4: a rework that could not run is recorded rather than looking like one that did."""
    report = a_report(
        version=2,
        revisions=(a_turn(reply="The model could not be reached.", changed=(), reworked=False),),
    )

    assert report.revisions[0].reworked is False
