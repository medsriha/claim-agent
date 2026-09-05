"""Turning a screening or an investigation into the report somebody acts on (FR-2.1, FR-0.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001
from tests.unit.test_agent_investigate import a_conclusion
from tests.unit.test_report_render import a_context, a_line, a_stopped_claim

from claim_agent.agent.budget import BudgetSnapshot
from claim_agent.agent.revise import ClaimFindingsRevision, ClaimRevision
from claim_agent.agent.run import ClaimInvestigation
from claim_agent.agent.schemas import ClaimSplit
from claim_agent.agent.triage import ClaimTriage
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, build_claim_lines
from claim_agent.domain.decision import DecisionStage
from claim_agent.domain.models import (
    Attachment,
    Case,
    GateName,
    Order,
    Shipment,
    TerminalReason,
    Verdict,
)
from claim_agent.domain.outcome import OutcomeDecision, Recommendation
from claim_agent.preflight.models import CaseRecord, GateResult, PreflightResult
from claim_agent.report.build import (
    build_investigation_report,
    build_revised_report,
    build_screening_report,
)
from claim_agent.report.conversation import _findings_became_the_next_version
from claim_agent.report.models import (
    InvestigationReportContent,
    Report,
    ReportState,
    ScreeningReportContent,
)
from claim_agent.report.review import send_back

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


def two_damaged_products() -> tuple[ClaimLine, ...]:
    """Two products on one claim, matched to the order the way the split matches them."""
    return build_claim_lines(
        CASE.case_id,
        [
            ClaimedProduct(name=COLLAGEN, sku="COLLAGEN1", quantity=1),
            ClaimedProduct(name="Additional Collagen Ampoule Duo", sku="AMP1", quantity=1),
        ],
        ORDER,
    )


# --- A claim the quick checks stopped (FR-0.4, FR-C.1) -----------------------


def test_a_stopped_claim_is_written_up_as_a_report_about_the_whole_claim() -> None:
    """FR-C.1: the split happens later, so a stopped claim has no product to name."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.product_names == ()
    assert report.stage is DecisionStage.SCREENING
    assert report.case_id == CASE.case_id


def test_a_stopped_claim_recommends_nothing() -> None:
    """FR-2.1: the three actions are about a damaged product, and there is none."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.recommendation is None
    assert report.amount_usd is None
    assert report.confidence is None


def test_a_stopped_claim_carries_the_reasons_it_was_stopped() -> None:
    """FR-0.4: the report exposes the stopped claim's facts for the UI to render."""
    screening = a_stopped_screening()
    report = build_screening_report(screening, at=A_MOMENT)

    assert report is not None
    assert screening.report is not None
    assert isinstance(report.content, ScreeningReportContent)
    assert report.content.reasons == (TerminalReason.CLAIM_TOO_OLD,)
    assert report.content.findings == screening.report.findings
    assert report.content.gates == screening.report.gates


def test_a_claim_the_checks_let_through_has_no_screening_report() -> None:
    """FR-0.4: only a stopped claim produces one; the rest come from the investigation."""
    assert build_screening_report(a_passing_screening(), at=A_MOMENT) is None


def test_the_merchant_is_named_by_the_identifier_that_stays_the_same() -> None:
    """FR-3.8: keyed on user_id, never on the display name."""
    report = build_screening_report(a_stopped_screening(), at=A_MOMENT)

    assert report is not None
    assert report.user_id == CASE.user_id


# --- One report per claim (FR-2.1, FR-2.9b) ----------------------------------


def test_fr_2_9b_a_claim_gets_one_report_naming_every_damaged_product() -> None:
    """FR-2.9b: a claim is investigated once and approved once, however many products."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")),
        findings=a_line(lines=two_damaged_products()),
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.stage is DecisionStage.INVESTIGATION
    assert report.report_id == f"RPT-{CASE.case_id}"
    assert len(report.product_names) == 2


def test_a_report_carries_what_was_recommended_and_for_how_much() -> None:
    """FR-2.1: the list of a claim's reports draws its row from these."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), findings=a_line()
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.recommendation is Recommendation.APPROVE
    assert report.amount_usd == Decimal("52.00")
    assert report.state is ReportState.AWAITING_REVIEW
    assert report.decided is None


def test_a_report_keeps_findings_separate_from_the_itemized_merchant_request() -> None:
    """The report summarizes why; the email alone presents every requested item."""
    finding = "The evidence is incomplete and the invoice does not correspond to this shipment."
    detail = "an invoice corresponding to this shipment"
    line = a_line(
        conclusion=a_conclusion(reasoning=finding),
        outcome=a_line().outcome.model_copy(
            update={
                "recommendation": Recommendation.REQUEST_INFO,
                "recommended_by_agent": Recommendation.REQUEST_INFO,
            }
        ),
        requested_details=(detail,),
    )
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")),
        findings=line,
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert isinstance(report.content, InvestigationReportContent)
    assert report.content.finding_summary == finding
    assert report.content.requested_details == (detail,)


def test_a_report_embeds_the_claim_image_urls_for_the_representative() -> None:
    """FR-2.2: the report is self-contained enough to open every image it references."""
    image = Attachment(
        attachment_id="ATT-CASE-1001-03",
        file_name="damaged-collagen.png",
        content_type="image/png",
        url="https://images.example.test/damaged-collagen.png",
    )
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")).model_copy(update={"attachments": (image,)}),
        findings=a_line(),
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert isinstance(report.content, InvestigationReportContent)
    assert report.content.attachments == (image,)
    assert report.model_dump(mode="json")["content"]["attachments"][0]["url"] == image.url


def test_a_run_that_never_concluded_reports_no_confidence_rather_than_low_confidence() -> None:
    """FR-1.15: nothing was concluded, so there is nothing to be sure about."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage((COLLAGEN, "COLLAGEN1")),
        findings=a_line(conclusion=None),
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.confidence is None


def test_an_internal_split_ambiguity_produces_a_rep_clarification_report() -> None:
    """An ambiguity without a concrete merchant request stays with the representative."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage().model_copy(update={"ambiguity": "Two products look alike."}),
        findings=None,
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert report.product_names == ()
    assert report.drafted_email is None
    assert report.content.kind == "clarification"


def test_a_merchant_resolvable_split_requests_details_and_drafts_the_email() -> None:
    """An ambiguous split goes to the merchant when the agent knows exactly what to ask."""
    detail = "a clear photograph showing the damaged bottle's front label"
    split = ClaimSplit(
        is_ambiguous=True,
        ambiguity="The photograph could show either of two 24oz bottles.",
        requested_details=(detail,),
        email_subject="More information needed for your claim",
        email_body=f"Please send {detail}.",
        reasoning="The label is not legible.",
    )
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage().model_copy(update={"ambiguity": split.ambiguity, "split": split}),
        findings=None,
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.recommendation is Recommendation.REQUEST_INFO
    assert report.product_names == ()
    assert report.drafted_email is not None
    assert detail in report.drafted_email.body
    assert report.content.kind == "clarification"
    assert report.content.requested_details == (detail,)


def test_an_unsafe_split_email_falls_back_to_the_representative() -> None:
    """Unsafe merchant wording is never surfaced merely because the split requested details."""
    split = ClaimSplit(
        is_ambiguous=True,
        ambiguity="The photograph does not identify the bottle.",
        requested_details=("a clear photograph of the bottle's front label",),
        email_subject="More information needed",
        email_body="Please send a clearer image; the possible item costs $12.99.",
        reasoning="The label is unreadable.",
    )
    investigation = ClaimInvestigation(
        case_id=CASE.case_id,
        triage=a_triage().model_copy(update={"ambiguity": split.ambiguity, "split": split}),
        findings=None,
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert report.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert report.drafted_email is None
    assert report.content.kind == "clarification"
    assert report.content.requested_details == ()


# --- The next version, after a representative sent it back (FR-R.9, FR-R.13) ---


def a_report_to_rework() -> Report:
    """One investigated claim's report, as it stands when a note arrives."""
    return build_investigation_report(
        a_passing_screening(),
        ClaimInvestigation(
            case_id=CASE.case_id,
            triage=a_triage((COLLAGEN, "COLLAGEN1")),
            findings=a_line(),
        ),
        at=A_MOMENT,
    )


def a_rework(**overrides: Any) -> ClaimFindingsRevision:
    """What a rework produced, with everything a test does not care about defaulted."""
    fields: dict[str, Any] = {
        "findings": a_line(
            outcome=OutcomeDecision(
                recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
                recommended_by_agent=Recommendation.REQUEST_REP_CLARIFICATION,
                explanation="The outer packaging was never photographed after all.",
            ),
            drafted_email=None,
            concerns=("The image thought to be the box is the product itself.",),
        ),
        "reply": "You were right about the packaging photograph.",
        "changed": ("Marked the outer packaging photograph missing.",),
        "left_unchanged": ("The invoice, which the note did not bear on.",),
    }
    fields.update(overrides)
    return ClaimFindingsRevision.model_validate(fields)


def test_fr_r_13_a_rework_produces_the_next_version_and_leaves_the_last_one_alone() -> None:
    """FR-R.13: reworking a report must leave the version the rep was looking at intact."""
    before = a_report_to_rework()

    after = build_revised_report(before, a_rework(), feedback="Look at the box again.", at=A_MOMENT)

    assert after.report_id == before.report_id
    assert after.version == before.version + 1
    assert before.version == 1
    assert before.content != after.content


def test_fr_r_13_the_note_and_what_changed_are_kept_as_a_round_of_the_conversation() -> None:
    """FR-R.13: the feedback that prompted each revision and what changed are both kept."""
    after = build_revised_report(
        a_report_to_rework(), a_rework(), feedback="Look at the box again.", at=A_MOMENT
    )

    assert len(after.revisions) == 1
    turn = after.revisions[0]
    assert turn.turn == 1
    assert turn.from_version == 1
    assert turn.feedback == "Look at the box again."
    assert turn.reply == "You were right about the packaging photograph."
    assert turn.changed == ("Marked the outer packaging photograph missing.",)
    assert turn.reworked


def test_fr_r_12_a_second_round_is_added_to_the_first_rather_than_replacing_it() -> None:
    """FR-R.12: each cycle carries the full feedback history."""
    once = build_revised_report(
        a_report_to_rework(), a_rework(), feedback="Look at the box again.", at=A_MOMENT
    )

    twice = build_revised_report(once, a_rework(), feedback="Now the amount.", at=A_MOMENT)

    assert [turn.feedback for turn in twice.revisions] == [
        "Look at the box again.",
        "Now the amount.",
    ]
    assert [turn.turn for turn in twice.revisions] == [1, 2]
    assert twice.version == 3


def test_fr_r_9_the_next_version_carries_the_reworked_findings_and_email() -> None:
    """FR-R.9, FR-R.11: a full report in the same structure, with its email rewritten."""
    after = build_revised_report(
        a_report_to_rework(), a_rework(), feedback="Look at the box again.", at=A_MOMENT
    )

    assert after.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert after.amount_usd is None
    assert after.drafted_email is None
    assert isinstance(after.content, InvestigationReportContent)
    assert "the product itself" in after.content.concerns[0]


def test_a_reworked_report_goes_back_to_a_person_to_decide_on() -> None:
    """FR-2.9: approving is still the only way out, so a reworked report awaits review."""
    after = build_revised_report(
        a_report_to_rework(), a_rework(), feedback="Look at the box again.", at=A_MOMENT
    )

    assert after.state is ReportState.AWAITING_REVIEW


def test_a_rework_that_did_not_happen_leaves_every_finding_as_it_was() -> None:
    """NFR-4: a model that could not be reached must not degrade a sound report."""
    before = a_report_to_rework()

    after = build_revised_report(
        before,
        ClaimFindingsRevision(findings=None, reply="The model could not be reached."),
        feedback="Look at the box again.",
        at=A_MOMENT,
    )

    assert after.content == before.content
    assert after.recommendation == before.recommendation
    assert after.drafted_email == before.drafted_email
    assert after.version == before.version + 1
    assert after.revisions[0].reworked is False
    assert after.revisions[0].reply == "The model could not be reached."


def test_what_a_representative_already_decided_travels_with_the_next_version() -> None:
    """FR-C.1: a rework is not a fresh start, and the record of a decision must survive it."""
    before = a_report_to_rework()
    parked = send_back(before, feedback="Look at the box again.", at=A_MOMENT).report

    after = build_revised_report(parked, a_rework(), feedback="Look at the box again.", at=A_MOMENT)

    assert after.decisions_taken == 1
    assert after.reviews[0].rep_words == "Look at the box again."


# --- The same findings always produce the same report (NFR-1) ----------------


def test_the_same_claim_always_gets_the_same_report_name() -> None:
    """FR-C.4: investigating a claim again writes over its report rather than adding a second."""
    investigation = ClaimInvestigation(
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), findings=a_line()
    )

    first = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)
    again = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

    assert first == again
    # The same name a stopped claim would get, because both are about the claim. The two
    # can never collide: a claim the checks stopped is never investigated.
    assert first.report_id == f"RPT-{CASE.case_id}"


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
        case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), findings=a_line()
    )

    report = build_investigation_report(a_passing_screening(), investigation, at=A_MOMENT)

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


def test_a_stopped_claim_never_has_investigated_findings_folded_into_it() -> None:
    """FR-0.4, NFR-4: a report that cannot be read back is worse than one that never changed.

    Copying fields onto a report does not re-run the checks that it is internally consistent —
    those run when a report is built, and again when one is read out of the store. So a
    stopped claim given findings about products would be stored happily and fail the moment a
    representative asked for it back. It is unreachable today and refused anyway.
    """
    stopped = build_screening_report(a_stopped_screening(), at=A_MOMENT)
    assert stopped is not None
    investigated = build_investigation_report(
        a_passing_screening(),
        ClaimInvestigation(
            case_id=CASE.case_id, triage=a_triage((COLLAGEN, "COLLAGEN1")), findings=a_line()
        ),
        at=A_MOMENT,
    )

    after = _findings_became_the_next_version(
        stopped, investigated, ClaimRevision(reply="x"), feedback="Look again.", at=A_MOMENT
    )

    assert after.content.kind == "screening"
    assert after.product_names == ()
    # Written down and read back, which is where the inconsistency would have surfaced.
    assert Report.model_validate(after.model_dump()) == after
