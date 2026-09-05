"""Turning a screening or an investigation into reports somebody can act on (FR-2.1, FR-0.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001
from tests.unit.test_report_render import a_context, a_line, a_stopped_claim

from claim_agent.agent.budget import BudgetSnapshot
from claim_agent.agent.run import ClaimInvestigation
from claim_agent.agent.triage import ClaimTriage
from claim_agent.domain.claim_line import ClaimedProduct, build_claim_lines
from claim_agent.domain.decision import DecisionStage
from claim_agent.domain.models import (
    Case,
    GateName,
    Order,
    Shipment,
    TerminalReason,
    Verdict,
)
from claim_agent.domain.outcome import Recommendation
from claim_agent.preflight.models import CaseRecord, GateResult, PreflightResult
from claim_agent.report.build import build_investigation_reports, build_screening_report
from claim_agent.report.models import ReportState

CASE = Case.model_validate(CASE_1001)
ORDER = Order.model_validate(ORDER_1001)
SHIPMENT = Shipment.model_validate(SHIPMENT_1001)
RECORD = CaseRecord(case=CASE, shipment=SHIPMENT, order=ORDER)
A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)
COLLAGEN = "Liposomal Tripeptide Collagen"


def a_gate(passed: bool) -> GateResult:
    """One of the four quick checks, so a result can be built without writing all four."""
    return GateResult(
        gate=GateName.AGE,
        passed=passed,
        reason=None if passed else TerminalReason.CLAIM_TOO_OLD,
        explanation="Filed 4 days after delivery." if passed else "Filed 73 days after delivery.",
        observed={"days_since_delivery": "4" if passed else "73"},
    )


def a_stopped_screening(**overrides: Any) -> PreflightResult:
    """A claim the quick checks turned away."""
    fields: dict[str, Any] = {
        "case_id": CASE.case_id,
        "verdict": Verdict.TERMINAL,
        "terminal_reasons": (TerminalReason.CLAIM_TOO_OLD,),
        "gates": (a_gate(passed=False),),
        "record": RECORD,
        "context": a_context(days_since_delivery=73),
        "report": a_stopped_claim(case_id=CASE.case_id, user_id=CASE.user_id),
        "evaluated_at": A_MOMENT,
    }
    fields.update(overrides)
    return PreflightResult(**fields)


def a_passing_screening() -> PreflightResult:
    """A claim the quick checks let through, which carries no write-up of its own."""
    return PreflightResult(
        case_id=CASE.case_id,
        verdict=Verdict.PROCEED,
        gates=(a_gate(passed=True),),
        record=RECORD,
        context=a_context(),
        evaluated_at=A_MOMENT,
    )


def a_triage(*products: tuple[str, str]) -> ClaimTriage:
    """A settled split into the named products."""
    return ClaimTriage(
        case_id=CASE.case_id,
        claim_lines=tuple(
            build_claim_lines(
                CASE.case_id,
                [ClaimedProduct(name=name, sku=sku, quantity=1) for name, sku in products],
                ORDER,
            )
        ),
        budget=BudgetSnapshot(
            steps_used=1,
            steps_allowed=12,
            image_analyses_used=0,
            image_analyses_allowed=20,
            tool_retries_used=0,
            tool_retries_allowed_per_call=2,
            limits_reached=(),
        ),
    )


# --- A claim the quick checks stopped (FR-0.4, FR-C.1) -----------------------


def test_a_stopped_claim_is_written_up_as_a_report_about_the_whole_claim() -> None:
    """FR-C.1: the split happens later, so a stopped claim has no product to name."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.claim_line_id is None
    assert report.stage is DecisionStage.SCREENING
    assert report.case_id == CASE.case_id


def test_a_stopped_claim_recommends_nothing() -> None:
    """FR-2.1: the four recommendations are about a damaged product, and there is none."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.recommendation is None
    assert report.amount_usd is None
    assert report.confidence is None


def test_a_stopped_claim_carries_the_reasons_it_was_stopped() -> None:
    """FR-0.4: the report a rep approves is the explanation the merchant is owed."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert "claim too old" in report.markdown
    assert "## The four checks" in report.markdown


def test_a_claim_the_checks_let_through_has_no_screening_report() -> None:
    """FR-0.4: only a stopped claim produces one; the rest come from the investigation."""
    assert build_screening_report(a_passing_screening(), at=A_MOMENT) is None


def test_the_merchant_is_named_by_the_identifier_that_stays_the_same() -> None:
    """FR-3.8: keyed on user_id, never on the display name."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.user_id == CASE.user_id


# --- One report per damaged product (FR-2.1, FR-3.1a) ------------------------


def test_each_damaged_product_gets_its_own_report() -> None:
    """FR-3.1a: approval is per product, so each is approved or sent back on its own."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")),
        lines=(a_line(), a_line()),
    )

    reports = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)

    assert len(reports) == 2
    assert all(report.stage is DecisionStage.INVESTIGATION for report in reports)
    assert all(report.claim_line_id is not None for report in reports)


def test_a_report_carries_what_was_recommended_and_for_how_much() -> None:
    """FR-2.1: the list of a claim's reports draws its row from these."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), lines=(a_line(),)
    )

    (report,) = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.recommendation is Recommendation.APPROVE
    assert report.amount_usd == Decimal("52.00")
    assert report.state is ReportState.AWAITING_REVIEW
    assert report.decided is None


def test_a_run_that_never_concluded_reports_no_confidence_rather_than_low_confidence() -> None:
    """FR-1.15: nothing was concluded, so there is nothing to be sure about."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")),
        lines=(a_line(conclusion=None),),
    )

    (report,) = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.confidence is None


def test_a_split_that_could_not_be_settled_produces_no_reports() -> None:
    """FR-1a.4: nothing was established about any product, so there is nothing to approve."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage().model_copy(update={"ambiguity": "Two products look alike."}),
        lines=(),
    )

    assert build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT) == ()


# --- The same findings always produce the same report (NFR-1) ----------------


def test_the_same_product_always_gets_the_same_report_name() -> None:
    """FR-C.4: investigating a product again writes over its report rather than adding a second."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), lines=(a_line(),)
    )

    first = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)
    again = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)

    assert first == again
    assert first[0].report_id == f"RPT-{first[0].claim_line_id}"


def test_a_stopped_claim_always_gets_the_same_report_name() -> None:
    """FR-C.4: screening a claim again writes over its report rather than adding a second."""
    first = build_screening_report(a_stopped_screening(), at=A_MOMENT)
    again = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert first == again
    assert first is not None
    assert first.report_id == f"RPT-{CASE.case_id}"


# --- What the merchant said, read out of their own description ---------------


def test_what_the_merchant_reported_is_read_out_of_the_description() -> None:
    """FR-C.1: these are among the few things about a claim known before anybody looks."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), lines=(a_line(),)
    )

    (report,) = build_investigation_reports(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.defect_type == "Both product and shipping box damaged"
    assert report.damage_type == "Damage due to poor/bad packaging"


def test_who_carried_the_parcel_comes_from_the_shipment_not_the_description() -> None:
    """FR-C.1: the description and the shipment can name different carriers, and the record
    keeps the one ShipBob holds rather than the one the merchant wrote."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.carrier == SHIPMENT.carrier


def test_a_claim_with_no_shipment_record_names_no_carrier() -> None:
    """FR-0.5: missing is not the same as empty, and neither is a parcel nobody carried."""
    screening = a_stopped_screening(
        record=CaseRecord(case=CASE, shipment=None, order=ORDER),
        gates=(a_gate(passed=False),),
    )

    report = build_screening_report(screening, at=A_MOMENT)

    assert report is not None
    assert report.carrier is None
