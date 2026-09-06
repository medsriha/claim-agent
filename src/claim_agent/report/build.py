from __future__ import annotations

from claim_agent.agent.email import finish_email
from claim_agent.agent.investigate import ClaimFindings
from claim_agent.agent.revise import (
    AnswerRevision,
    ClaimFindingsRevision,
    ClaimRevision,
    EmailRevision,
)
from claim_agent.agent.run import ClaimInvestigation
from claim_agent.domain.case_facts import read_case_facts
from claim_agent.domain.decision import DecisionStage
from claim_agent.domain.models import Attachment, Case, UtcDatetime
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ModelOutputRejectedError
from claim_agent.observability import get_logger
from claim_agent.preflight.models import ClaimContext, PreflightResult
from claim_agent.report.models import (
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ReportState,
    RevisionTurn,
    ScreeningReportContent,
)

logger = get_logger(__name__)


def report_id_for_claim(case_id: str) -> str:
    """Name the report for a claim, the same way every time."""
    return f"RPT-{case_id}"


def build_screening_report(screening: PreflightResult, *, at: UtcDatetime) -> Report | None:
    """Write up a claim the quick checks turned away (FR-0.4, FR-C.1)."""
    if screening.report is None:
        return None

    described = read_case_facts(screening.record.case)
    return Report(
        report_id=report_id_for_claim(screening.case_id),
        version=1,
        case_id=screening.case_id,
        product_names=(),
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


def build_investigation_report(
    screening: PreflightResult,
    investigation: ClaimInvestigation,
    *,
    at: UtcDatetime,
) -> Report:
    """Write up what the investigation found on one claim (FR-2.1 to FR-2.7)."""
    if investigation.findings is None:
        return _claim_clarification(screening, investigation, at=at)

    return report_for_the_claim(
        findings=investigation.findings,
        case=screening.record.case,
        carrier=_carrier(screening),
        context=screening.context,
        attachments=investigation.triage.attachments,
        at=at,
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

    concerns = triage.split.concerns if triage.split is not None else ()

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
            concerns = (*concerns, refused.message)
        else:
            recommendation = Recommendation.REQUEST_INFO
            report_details = requested_details

    return Report(
        report_id=report_id_for_claim(screening.case_id),
        version=1,
        case_id=screening.case_id,
        product_names=(),
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


def report_for_the_claim(
    *,
    findings: ClaimFindings,
    case: Case,
    carrier: str | None,
    context: ClaimContext,
    attachments: tuple[Attachment, ...],
    at: UtcDatetime,
) -> Report:
    """Write a claim's findings into a report."""
    described = read_case_facts(case)
    return Report(
        report_id=report_id_for_claim(case.case_id),
        version=1,
        case_id=case.case_id,
        product_names=tuple(line.product_name for line in findings.lines),
        account_name=case.account_name,
        user_id=case.user_id,
        stage=DecisionStage.INVESTIGATION,
        state=ReportState.AWAITING_REVIEW,
        recommendation=findings.outcome.recommendation,
        amount_usd=(
            findings.amount.amount_usd if findings.outcome.recommendation.is_approval else None
        ),
        confidence=None,
        carrier=carrier,
        defect_type=described.defect_type,
        damage_type=described.damage_type,
        order_value_usd=context.order_value_usd,
        decided=None,
        decisions_taken=0,
        drafted_email=findings.drafted_email,
        content=InvestigationReportContent(
            lines=findings.lines,
            context=context,
            attachments=attachments,
            evidence=findings.evidence,
            assessments=findings.assessments,
            outcome=findings.outcome,
            amount=findings.amount,
            concerns=findings.concerns,
            requested_details=findings.requested_details,
            finding_summary=_finding_summary(findings),
            corrections_considered=(
                findings.conclusion.corrections_considered
                if findings.conclusion is not None
                else ()
            ),
            thread_id=findings.thread_id,
            prompt_version=findings.prompt_version,
            model=findings.model,
            budget=findings.budget,
        ),
        created_at=at,
    )


def build_revised_report(
    report: Report,
    revision: ClaimFindingsRevision | ClaimRevision | EmailRevision | AnswerRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    reinvestigated: bool = False,
) -> Report:
    """Write the next version of a report after a representative sent it back (FR-R.9, FR-R.13)."""
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

    if isinstance(revision, EmailRevision):
        return report.model_copy(update={**carried_forward, "drafted_email": revision.email})

    if isinstance(revision, ClaimRevision):
        return _a_claim_level_version(report, revision, carried_forward=carried_forward)

    if isinstance(revision, AnswerRevision):
        return report.model_copy(update=carried_forward)

    reworked = revision.findings
    if reworked is None:
        return report.model_copy(update=carried_forward)

    content = report.content
    if not isinstance(content, InvestigationReportContent):
        logger.warning("revised_report_has_no_investigation", report_id=report.report_id)
        return report.model_copy(update=carried_forward)

    return report.model_copy(
        update={
            **carried_forward,
            "product_names": tuple(line.product_name for line in reworked.lines),
            "recommendation": reworked.outcome.recommendation,
            "amount_usd": (
                reworked.amount.amount_usd if reworked.outcome.recommendation.is_approval else None
            ),
            "drafted_email": reworked.drafted_email,
            "content": content.model_copy(
                update={
                    "lines": reworked.lines,
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
                    "thread_id": reworked.thread_id or content.thread_id,
                    "prompt_version": reworked.prompt_version,
                    "model": reworked.model,
                    "budget": reworked.budget,
                }
            ),
        }
    )


def _a_claim_level_version(
    report: Report, revision: ClaimRevision, *, carried_forward: dict[str, object]
) -> Report:
    """Write the next version of a report that names no product (FR-1a.4, FR-0.4)."""
    content = report.content

    if isinstance(content, ScreeningReportContent):
        if revision.email is None or report.drafted_email is None:
            return report.model_copy(update=carried_forward)
        return report.model_copy(update={**carried_forward, "drafted_email": revision.email})

    if not isinstance(content, ClarificationReportContent) or not revision.reworked:
        return report.model_copy(update=carried_forward)

    if revision.directed is not None:
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


def _finding_summary(findings: ClaimFindings) -> str:
    """Keep the agent's concise finding while merchant asks remain in the email only."""
    if findings.conclusion is not None and findings.conclusion.reasoning.strip():
        return findings.conclusion.reasoning.strip()
    return findings.outcome.explanation


def _carrier(screening: PreflightResult) -> str | None:
    """Who carried the parcel, as ShipBob names them."""
    if screening.record.shipment is None:
        return None
    return screening.record.shipment.carrier
