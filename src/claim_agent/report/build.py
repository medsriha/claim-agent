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

from claim_agent.agent.email import finish_email
from claim_agent.agent.investigate import LineInvestigation
from claim_agent.agent.revise import ClaimRevision, LineRevision
from claim_agent.agent.run import ClaimInvestigation
from claim_agent.domain.case_facts import read_case_facts
from claim_agent.domain.decision import DecisionStage
from claim_agent.domain.models import Attachment, Case, UtcDatetime
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ModelOutputRejectedError
from claim_agent.observability import get_logger
from claim_agent.preflight.models import ClaimContext, PreflightResult
from claim_agent.report.models import (
    ClaimView,
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ReportState,
    RevisionTurn,
    ScreeningReportContent,
    SiblingLine,
)

logger = get_logger(__name__)


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

    It also recommends nothing. The next actions are about a damaged product and there is
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
    unclear which products are being claimed for (FR-1a.4). The report names the ambiguity and
    asks the merchant for concrete missing details when they can resolve it; otherwise it asks
    the representative. Neither path invents a product.

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
        report_for_one_product(
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
    """Report an unsettled split, asking the merchant when they can resolve it."""
    described = read_case_facts(screening.record.case)
    triage = investigation.triage
    ambiguity = triage.ambiguity or "The investigation could not establish a claimable product."
    requested_details = triage.split.requested_details if triage.split is not None else ()
    recommendation = Recommendation.REQUEST_REP_CLARIFICATION
    drafted_email = None
    report_details: tuple[str, ...] = ()
    concerns = (ambiguity, *investigation.claim_concerns)

    if requested_details and triage.split is not None:
        try:
            drafted_email = finish_email(
                triage.split,
                recommendation=Recommendation.REQUEST_INFO,
                amount=None,
                contact_email=screening.record.case.contact_email,
                requested_details=requested_details,
            )
        except ModelOutputRejectedError as refused:
            logger.warning(
                "claim_split_email_refused",
                case_id=screening.case_id,
            )
            concerns = (ambiguity, refused.message, *investigation.claim_concerns)
        else:
            recommendation = Recommendation.REQUEST_INFO
            report_details = requested_details

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
        recommendation=recommendation,
        amount_usd=None,
        confidence=None,
        carrier=_carrier(screening),
        defect_type=described.defect_type,
        damage_type=described.damage_type,
        order_value_usd=screening.context.order_value_usd,
        decided=None,
        decisions_taken=0,
        drafted_email=drafted_email,
        content=ClarificationReportContent(
            context=screening.context,
            attachments=triage.attachments,
            candidate_lines=triage.claim_lines,
            ambiguity=ambiguity,
            concerns=concerns,
            requested_details=report_details,
        ),
        created_at=at,
    )


def report_for_one_product(
    *,
    line: LineInvestigation,
    case: Case,
    carrier: str | None,
    context: ClaimContext,
    attachments: tuple[Attachment, ...],
    at: UtcDatetime,
) -> Report:
    """Write one damaged product's findings into a report.

    Used both by an investigation writing up every product it looked into, and by a
    representative naming a product on a claim nobody could split — the second produces exactly
    the same kind of report, so it is written by exactly the same function (FR-1a.4).

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
        amount_usd=(line.amount.amount_usd if line.outcome.recommendation.is_approval else None),
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
            finding_summary=_finding_summary(line),
            corrections_considered=(
                line.conclusion.corrections_considered if line.conclusion is not None else ()
            ),
        ),
        created_at=at,
    )


def build_revised_report(
    report: Report,
    revision: LineRevision | ClaimRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    reinvestigated: bool = False,
) -> Report:
    """Write the next version of a report after a representative sent it back (FR-R.9, FR-R.13).

    A whole report, not a patch. It has the same name and the same identity as the one before
    it, one higher version number, and the conversation so far with one more round on the end.
    The version the representative was looking at is left exactly as it was — reading it back is
    how somebody sees what they saw when they decided.

    The report comes back **awaiting review** whatever happened, because approving is still the
    only way out and a reworked report has to be decided on by a person like any other (FR-2.9).

    What a representative already did to this report travels with it: how many decisions have
    been taken on it, and what each of them was. A rework is not a fresh start, and losing that
    record would lose the audit trail of where a human intervened (FR-C.1).

    Args:
        report: The report as it stood when the note arrived.
        revision: What the rework produced, or that it did not happen.
        feedback: What the representative said, in their own words, kept exactly as written.
        at: When this version is being written. Handed in rather than read from a clock, so the
            same rework writes the same version twice (NFR-1).
        reinvestigated: Whether this round also caused the whole claim to be investigated
            again, which produces a report per damaged product beside this one. Recorded on
            the round so a screen can go and show them (FR-1a.4).

    Returns:
        The next version. **When the rework did not happen the findings are the previous ones,
        unchanged**, and the turn on it says so — a model that could not be reached must not be
        allowed to degrade a sound report, and a representative must not be left with an error
        page instead of the work they were deciding on (NFR-4).
    """
    turn = RevisionTurn(
        turn=len(report.revisions) + 1,
        from_version=report.version,
        feedback=feedback,
        reply=revision.reply,
        changed=revision.changed,
        left_unchanged=revision.left_unchanged,
        needs_reply=revision.needs_reply,
        reworked=revision.reworked,
        reinvestigated=reinvestigated,
    )
    carried_forward = {
        "version": report.version + 1,
        "state": ReportState.AWAITING_REVIEW,
        "revisions": (*report.revisions, turn),
        "created_at": at,
    }

    if isinstance(revision, ClaimRevision):
        return _a_claim_level_version(report, revision, carried_forward=carried_forward)

    reworked = revision.investigation
    if reworked is None:
        return report.model_copy(update=carried_forward)

    content = report.content
    if not isinstance(content, InvestigationReportContent):
        # A product rework only ever runs on a product's report, and the route sends anything
        # else down the claim-level path above. Reaching here would mean that split was
        # removed, so the findings are left alone rather than rebuilt from a shape they do not
        # fit.
        logger.warning("revised_report_has_no_investigation", report_id=report.report_id)
        return report.model_copy(update=carried_forward)

    return report.model_copy(
        update={
            **carried_forward,
            "recommendation": reworked.outcome.recommendation,
            "amount_usd": (
                reworked.amount.amount_usd if reworked.outcome.recommendation.is_approval else None
            ),
            "confidence": reworked.confidence,
            "drafted_email": reworked.drafted_email,
            "content": content.model_copy(
                update={
                    "line": reworked.line,
                    "evidence": reworked.evidence,
                    "assessments": reworked.assessments,
                    "outcome": reworked.outcome,
                    "amount": reworked.amount,
                    "concerns": reworked.concerns,
                    "requested_details": reworked.requested_details,
                    "finding_summary": _finding_summary(reworked),
                    "corrections_considered": (
                        reworked.conclusion.corrections_considered
                        if reworked.conclusion is not None
                        else ()
                    ),
                }
            ),
        }
    )


def _a_claim_level_version(
    report: Report, revision: ClaimRevision, *, carried_forward: dict[str, object]
) -> Report:
    """Write the next version of a report that names no product (FR-1a.4, FR-0.4).

    Two kinds of report reach here, and what each may change is decided here rather than by
    what the agent wrote:

    - **A claim whose split was never settled** may have its ambiguity, its merchant requests,
      its recommendation and its email all reworked. A representative answering the question
      the report asked is the whole reason it was asked.
    - **A claim the quick checks turned away** may have only its merchant email reworded. Its
      verdict came from fixed rules, and feedback cannot overturn one (FR-0.6, FR-R.8), so
      every other field on the revision is ignored for it.

    A revision that changed nothing — an answer to a question, or a request for the claim to be
    investigated again — carries the report through untouched, with the round of conversation
    on it and nothing else.
    """
    content = report.content

    if isinstance(content, ScreeningReportContent):
        if revision.email is None or report.drafted_email is None:
            return report.model_copy(update=carried_forward)
        return report.model_copy(update={**carried_forward, "drafted_email": revision.email})

    if not isinstance(content, ClarificationReportContent) or not revision.reworked:
        return report.model_copy(update=carried_forward)

    return report.model_copy(
        update={
            **carried_forward,
            "recommendation": revision.recommendation,
            "drafted_email": revision.email,
            "content": content.model_copy(
                update={
                    "ambiguity": revision.ambiguity or content.ambiguity,
                    "requested_details": revision.requested_details,
                }
            ),
        }
    )


def _finding_summary(line: LineInvestigation) -> str:
    """Keep the agent's concise finding while merchant asks remain in the email only."""
    if line.conclusion is not None and line.conclusion.reasoning.strip():
        return line.conclusion.reasoning.strip()
    return line.outcome.explanation


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
