from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

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
    report = a_report(recommendation=Recommendation.APPROVE_HIGH_VALUE)

    assert report.recommendation is Recommendation.APPROVE_HIGH_VALUE
    assert report.amount_usd == Decimal("52.00")
    assert report.drafted_email is not None


def test_fr_c_7_a_high_value_approval_without_its_email_is_refused() -> None:
    with pytest.raises(ValidationError):
        a_report(recommendation=Recommendation.APPROVE_HIGH_VALUE, drafted_email=None)


def test_a_stopped_claim_names_no_damaged_product() -> None:
    report = a_screening_report()

    assert report.product_names == ()
    assert report.stage is DecisionStage.SCREENING


def test_a_stopped_claim_carrying_a_product_is_refused() -> None:
    with pytest.raises(ValidationError):
        a_screening_report(product_names=("Liposomal Tripeptide Collagen",))


def test_an_investigated_report_has_to_name_what_was_damaged() -> None:
    with pytest.raises(ValidationError):
        a_report(product_names=())


def test_a_stopped_claim_recommends_nothing_and_that_is_a_real_answer() -> None:
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
    with pytest.raises(ValidationError):
        a_screening_report(**invented)


def test_a_screening_clarification_request_cannot_carry_an_email() -> None:
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
    with pytest.raises(ValidationError, match="needs an email draft"):
        a_screening_report(drafted_email=None)


@pytest.mark.parametrize("recommendation", [Recommendation.APPROVE, Recommendation.REQUEST_INFO])
def test_a_merchant_facing_investigation_action_needs_an_email(
    recommendation: Recommendation,
) -> None:
    amount = Decimal("52.00") if recommendation is Recommendation.APPROVE else None

    with pytest.raises(ValidationError, match="needs an email draft"):
        a_report(recommendation=recommendation, amount_usd=amount, drafted_email=None)


def test_a_rep_clarification_action_may_keep_a_draft_for_the_representative() -> None:
    kept = a_report(recommendation=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None)

    assert kept.drafted_email is not None
    assert kept.amount_usd is None


def test_a_rep_clarification_action_needs_no_email() -> None:
    asked = a_report(
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
        amount_usd=None,
        drafted_email=None,
    )

    assert asked.drafted_email is None


def test_a_merchant_information_report_must_name_the_details_needed() -> None:
    report = a_report(recommendation=Recommendation.REQUEST_INFO, amount_usd=None)
    assert isinstance(report.content, InvestigationReportContent)
    content = report.content.model_copy(update={"requested_details": ()})

    with pytest.raises(ValidationError, match="specific details needed"):
        a_report(
            recommendation=Recommendation.REQUEST_INFO,
            amount_usd=None,
            content=content,
        )


def test_what_the_representative_settled_on_is_kept_beside_what_was_advised() -> None:
    report = a_report(
        state=ReportState.APPROVED,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    assert report.amount_usd == Decimal("52.00")
    assert report.decided is not None
    assert report.decided.amount_usd == Decimal("31.20")


def test_a_figure_on_a_report_nobody_approved_is_refused() -> None:
    with pytest.raises(ValidationError):
        a_report(decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")))


@pytest.mark.parametrize("impossible", [{"version": 0}, {"decisions_taken": -1}])
def test_a_count_below_its_floor_is_refused(impossible: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        a_report(**impossible)


def test_a_report_cannot_be_edited_in_place() -> None:
    report = a_report()

    with pytest.raises(ValidationError):
        cast(Any, report).state = ReportState.APPROVED

    moved_on = report.model_copy(update={"state": ReportState.APPROVED})
    assert report.state is ReportState.AWAITING_REVIEW
    assert moved_on.state is ReportState.APPROVED


def test_a_field_nobody_declared_is_refused() -> None:
    with pytest.raises(ValidationError):
        a_report(recommended_amount="52.00")


def test_a_report_survives_being_written_down_and_read_back() -> None:
    report = a_report(
        state=ReportState.APPROVED,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    read_back = Report.model_validate_json(report.model_dump_json())

    assert read_back == report


def test_money_is_written_down_as_text_rather_than_a_number() -> None:
    written = a_report().model_dump(mode="json")

    assert written["amount_usd"] == "52.00"


def test_a_report_is_structured_and_does_not_carry_a_second_prose_document() -> None:
    written = a_report().model_dump(mode="json")

    assert written["content"]["kind"] == "investigation"
    assert "markdown" not in written


def test_a_claim_nobody_has_asked_about_has_no_reports_and_that_is_ordinary() -> None:
    view = ClaimView(case_id="CASE-1001")

    assert view.reports == ()


def test_fr_2_9a_one_report_names_every_damaged_product_on_the_claim() -> None:
    report = a_report(product_names=("Liposomal Tripeptide Collagen", "Blue Razz Liquid Carnitine"))

    assert report.product_names == (
        "Liposomal Tripeptide Collagen",
        "Blue Razz Liquid Carnitine",
    )


def a_turn(**overrides: Any) -> RevisionTurn:
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
    assert a_report().revisions == ()


def test_the_rounds_of_a_conversation_have_to_be_numbered_in_order() -> None:
    with pytest.raises(ValidationError, match="numbered in order"):
        a_report(version=3, revisions=(a_turn(), a_turn(turn=3, from_version=2)))


def test_a_round_cannot_answer_a_version_that_did_not_exist_yet() -> None:
    with pytest.raises(ValidationError, match="this version"):
        a_report(version=2, revisions=(a_turn(from_version=3),))


def test_a_question_only_round_can_be_recorded_on_the_current_version() -> None:
    report = a_report(version=1, revisions=(a_turn(from_version=1, reworked=False),))

    assert report.revisions[0].from_version == report.version


def test_a_round_says_whether_the_report_was_actually_reworked() -> None:
    report = a_report(
        version=2,
        revisions=(a_turn(reply="The model could not be reached.", changed=(), reworked=False),),
    )

    assert report.revisions[0].reworked is False
