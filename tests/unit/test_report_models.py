"""What a report is, and the states it refuses to exist in (FR-2.1, FR-2.9, FR-C.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from claim_agent.domain.decision import DecisionStage, Proposal
from claim_agent.domain.models import DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.report.models import ClaimView, Report, ReportState, SiblingLine

A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)


def a_report(**overrides: Any) -> Report:
    """One investigated product's report, so a test writes down only the part it is about."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1001-L01",
        "version": 1,
        "case_id": "CASE-1001",
        "claim_line_id": "CASE-1001-L01",
        "product_name": "Liposomal Tripeptide Collagen",
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
        "markdown": "## Recommendation\n\nApprove — $52.00\n",
        "created_at": A_MOMENT,
    }
    fields.update(overrides)
    return Report(**fields)


def a_screening_report(**overrides: Any) -> Report:
    """A claim the quick checks turned away, which has no damaged product in it."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1004",
        "case_id": "CASE-1004",
        "claim_line_id": None,
        "product_name": None,
        "stage": DecisionStage.SCREENING,
        "recommendation": None,
        "amount_usd": None,
        "confidence": None,
    }
    fields.update(overrides)
    return a_report(**fields)


# --- A stopped claim names a whole claim, not a product (FR-C.1) --------------


def test_a_stopped_claim_names_no_damaged_product() -> None:
    """FR-C.1: the split into products happens later, so a stopped claim never has one."""
    report = a_screening_report()

    assert report.claim_line_id is None
    assert report.stage is DecisionStage.SCREENING


def test_a_stopped_claim_carrying_a_product_is_refused() -> None:
    """FR-C.1: a product on a claim that never reached the split is a mistake in our own code."""
    with pytest.raises(ValidationError):
        a_screening_report(claim_line_id="CASE-1004-L01")


def test_an_investigated_report_has_to_name_its_product() -> None:
    """FR-2.9a: without an id it cannot be told apart from a report about a whole claim."""
    with pytest.raises(ValidationError):
        a_report(claim_line_id=None)


# --- A stopped claim recommends nothing (FR-2.1) ------------------------------


def test_a_stopped_claim_recommends_nothing_and_that_is_a_real_answer() -> None:
    """FR-2.1: the four recommendations are about a damaged product, and there is none."""
    report = a_screening_report()

    assert report.recommendation is None
    assert report.amount_usd is None


@pytest.mark.parametrize(
    "invented",
    [
        {"recommendation": Recommendation.DENY},
        {"amount_usd": Decimal("52.00")},
    ],
)
def test_a_stopped_claim_given_a_recommendation_is_refused(invented: dict[str, Any]) -> None:
    """FR-2.1: turning a claim's reasons into a recommendation would invent an answer."""
    with pytest.raises(ValidationError):
        a_screening_report(**invented)


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


# --- The claim view (FR-2.9b) -------------------------------------------------


def test_a_claim_nobody_has_asked_about_has_no_reports_and_that_is_ordinary() -> None:
    """FR-2.9b: an empty list is a claim nobody investigated, not a store that failed."""
    view = ClaimView(case_id="CASE-1001")

    assert view.reports == ()


def test_a_sibling_row_carries_what_a_representative_needs_to_see_at_a_glance() -> None:
    """FR-2.9a: a rep approving one product should see the second is still waiting."""
    sibling = SiblingLine(
        claim_line_id="CASE-1001-L02",
        product_name="Blue Razz Liquid Carnitine",
        recommendation=Recommendation.REQUEST_INFO,
        amount_usd=None,
        state=ReportState.AWAITING_REVIEW,
    )

    assert sibling.state is ReportState.AWAITING_REVIEW
    assert sibling.amount_usd is None
