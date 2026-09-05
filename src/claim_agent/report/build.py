"""Turning settled findings into structured reports somebody can act on.

One report per damaged product, and one for a claim the quick checks turned away before it ever
had products in it (FR-2.1, FR-0.4). Every fact remains a named field so the UI can construct the
report without parsing or receiving a prose document.

Nothing here judges anything. Every recommendation, figure and concern was settled before this
was called, and this only writes them down.

Nothing here reads a clock either — the moment is handed in, so the same findings written twice
produce the same reports twice (NFR-1).
"""

from __future__ import annotations

from claim_agent.agent.investigate import LineInvestigation
from claim_agent.agent.run import ClaimInvestigation
from claim_agent.domain.case_facts import read_case_facts
from claim_agent.domain.decision import DecisionStage
from claim_agent.domain.models import Attachment, Case, UtcDatetime
from claim_agent.domain.outcome import Recommendation
from claim_agent.preflight.models import ClaimContext, PreflightResult
from claim_agent.report.models import (
    ClaimView,
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ReportState,
    ScreeningReportContent,
    SiblingLine,
)


def report_id_for_claim(case_id: str) -> str:
    """Name the report for a whole claim, the same way every time.

    Worked out from the claim rather than handed out fresh, so screening the same claim again
    writes over its own report instead of leaving two that disagree (FR-C.4). The same reasoning
    the store of past claims uses to name a record.
    """
    return f"RPT-{case_id}"


def report_id_for_product(claim_line_id: str) -> str:
    """Name the report for one damaged product, the same way every time."""
    return f"RPT-{claim_line_id}"


def build_screening_report(screening: PreflightResult, *, at: UtcDatetime) -> Report | None:
    """Write up a claim the quick checks turned away (FR-0.4, FR-C.1).

    A stopped claim has no damaged products in it — splitting a claim into products happens later
    and a stopped claim never gets there — so this report is about the whole claim, and names no
    product.

    It also recommends nothing. The three actions are about a damaged product and there is
    none; its reasons are what it has to say instead, and turning them into a recommendation would
    be the system inventing an answer nobody gave.

    Args:
        screening: What the quick checks decided.
        at: When this report is being written. Handed in rather than read from a clock, so the
            same screening writes the same report twice.

    Returns:
        The report, or `None` for a claim the checks let through — that claim's reports come from
        its investigation instead, one per damaged product.
    """
    if screening.report is None:
        return None

    described = read_case_facts(screening.record.case)
    return Report(
        report_id=report_id_for_claim(screening.case_id),
        version=1,
        case_id=screening.case_id,
        claim_line_id=None,
        product_name=None,
        account_name=screening.record.case.account_name,
        user_id=screening.report.user_id,
        stage=DecisionStage.SCREENING,
        state=ReportState.AWAITING_REVIEW,
        recommendation=None,
        amount_usd=None,
        confidence=None,
        carrier=_carrier(screening),
        defect_type=described.defect_type,
        damage_type=described.damage_type,
        order_value_usd=screening.context.order_value_usd,
        decided=None,
        decisions_taken=0,
        drafted_email=screening.report.drafted_email,
        content=ScreeningReportContent(
            context=screening.report.context,
            reasons=screening.report.reasons,
            findings=screening.report.findings,
            gates=screening.report.gates,
            requires_rep_clarification=screening.report.requires_rep_clarification,
        ),
        created_at=at,
    )


def build_investigation_reports(
    screening: PreflightResult,
    investigation: ClaimInvestigation,
    *,
    at: UtcDatetime,
) -> tuple[Report, ...]:
    """Write up every damaged product the investigation looked into (FR-2.1 to FR-2.7).

    One report each, because approval is per product and each is approved or sent back on its own
    (FR-3.1a).

    **A claim whose split could not be settled produces one claim-level clarification report.**
    Nothing was established about any product, because nothing may be investigated while it is
    unclear which products are being claimed for (FR-1a.4). The report therefore names the
    ambiguity and asks the representative to clarify it without inventing a product or an email.

    Args:
        screening: What the quick checks established, read for the claim itself and for the facts
            worked out before the AI ran (FR-0.5, FR-2.6).
        investigation: What the investigation concluded, product by product.
        at: When these reports are being written.

    Returns:
        One report per damaged product, in the order the investigation returned them, or one
        claim-level clarification report when the split could not be settled.
    """
    if not investigation.lines:
        return (_claim_clarification(screening, investigation, at=at),)

    return tuple(
        _one_product(
            line=line,
            case=screening.record.case,
            carrier=_carrier(screening),
            context=screening.context,
            attachments=investigation.triage.attachments,
            at=at,
        )
        for line in investigation.lines
    )


def _claim_clarification(
    screening: PreflightResult,
    investigation: ClaimInvestigation,
    *,
    at: UtcDatetime,
) -> Report:
    """Report an unsettled or incorrect claim split without drafting a merchant email."""
    described = read_case_facts(screening.record.case)
    triage = investigation.triage
    ambiguity = triage.ambiguity or "The investigation could not establish a claimable product."
    return Report(
        report_id=report_id_for_claim(screening.case_id),
        version=1,
        case_id=screening.case_id,
        claim_line_id=None,
        product_name=None,
        account_name=screening.record.case.account_name,
        user_id=screening.record.case.user_id,
        stage=DecisionStage.INVESTIGATION,
        state=ReportState.AWAITING_REVIEW,
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
        amount_usd=None,
        confidence=triage.split.confidence if triage.split is not None else None,
        carrier=_carrier(screening),
        defect_type=described.defect_type,
        damage_type=described.damage_type,
        order_value_usd=screening.context.order_value_usd,
        decided=None,
        decisions_taken=0,
        drafted_email=None,
        content=ClarificationReportContent(
            context=screening.context,
            attachments=triage.attachments,
            candidate_lines=triage.claim_lines,
            ambiguity=ambiguity,
            concerns=(ambiguity, *investigation.claim_concerns),
        ),
        created_at=at,
    )


def _one_product(
    *,
    line: LineInvestigation,
    case: Case,
    carrier: str | None,
    context: ClaimContext,
    attachments: tuple[Attachment, ...],
    at: UtcDatetime,
) -> Report:
    """Write one damaged product's findings into a report.

    `confidence` is read off the investigation's own conclusion rather than worked out here. It is
    `None` when the run never reached one, which must not be read as low confidence: nothing was
    concluded, so there is nothing to be sure about.
    """
    described = read_case_facts(case)
    return Report(
        report_id=report_id_for_product(line.line.claim_line_id),
        version=1,
        case_id=case.case_id,
        claim_line_id=line.line.claim_line_id,
        product_name=line.line.product_name,
        account_name=case.account_name,
        user_id=case.user_id,
        stage=DecisionStage.INVESTIGATION,
        state=ReportState.AWAITING_REVIEW,
        recommendation=line.outcome.recommendation,
        amount_usd=(
            line.amount.amount_usd
            if line.outcome.recommendation is Recommendation.APPROVE
            else None
        ),
        confidence=line.confidence,
        carrier=carrier,
        defect_type=described.defect_type,
        damage_type=described.damage_type,
        order_value_usd=context.order_value_usd,
        decided=None,
        decisions_taken=0,
        drafted_email=line.drafted_email,
        content=InvestigationReportContent(
            line=line.line,
            context=context,
            attachments=attachments,
            evidence=line.evidence,
            assessments=line.assessments,
            outcome=line.outcome,
            amount=line.amount,
            concerns=line.concerns,
            requested_details=line.requested_details,
            corrections_considered=(
                line.conclusion.corrections_considered if line.conclusion is not None else ()
            ),
        ),
        created_at=at,
    )


def siblings_of(report: Report, claim: ClaimView) -> tuple[SiblingLine, ...]:
    """The other damaged products on the same claim, as rows beside this one (FR-2.9a).

    A representative approving one product should be able to see that the second is still waiting
    on a photograph, without opening it.

    Worked out when a report is read rather than kept inside it. A sibling's review state changes
    the moment somebody approves that sibling, so a copy stored alongside this report would say
    "waiting" next to a product approved ten minutes ago.

    Args:
        report: The report being read. It is left out of its own siblings.
        claim: Every report on the claim, each at the version in force.

    Returns:
        One row per other product, in the order the claim reports them. Empty for a claim of one
        product, and empty for a claim the quick checks stopped — which has no products at all.
    """
    return tuple(
        SiblingLine(
            claim_line_id=other.claim_line_id,
            product_name=other.product_name,
            recommendation=other.recommendation,
            amount_usd=other.amount_usd,
            state=other.state,
        )
        for other in claim.reports
        if other.report_id != report.report_id
        and other.claim_line_id is not None
        and other.product_name is not None
    )


def _carrier(screening: PreflightResult) -> str | None:
    """Who carried the parcel, as ShipBob names them.

    Kept on the report because the record of what a representative decided groups decisions by it,
    and it is one of the few things about a claim known before anybody looks at it. `None` when the
    case named no shipment, or when the shipment could not be read — which is not the same as a
    parcel nobody carried.
    """
    if screening.record.shipment is None:
        return None
    return screening.record.shipment.carrier
