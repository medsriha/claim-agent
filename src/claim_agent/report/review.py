from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from claim_agent.domain.decision import DecisionRecord, Proposal, RepAction
from claim_agent.domain.models import DraftedEmail, UtcDatetime
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ConflictError
from claim_agent.policy import Policy
from claim_agent.report.models import EmailWording, Report, ReportReview, ReportState


@dataclass(frozen=True)
class ReviewOutcome:
    """What one review action produced: the report as it now stands, and the record of the act."""

    report: Report
    decision: DecisionRecord | None


def approve(
    report: Report,
    *,
    decided_outcome: Recommendation | None = None,
    decided_amount_usd: Decimal | None = None,
    edited_email: EmailWording | None = None,
    rep_words: str | None = None,
    rep_minutes: int = 0,
    policy: Policy,
    at: UtcDatetime,
) -> ReviewOutcome:
    """Accept a report, as it stands or after changing it (FR-2.8, FR-2.9, FR-C.1)."""
    settled = Proposal(
        outcome=decided_outcome if decided_outcome is not None else report.recommendation,
        amount_usd=decided_amount_usd if decided_amount_usd is not None else report.amount_usd,
    )

    if report.state is ReportState.APPROVED:
        return _already_approved(report, settled=settled, edited_email=edited_email)

    sequence = report.decisions_taken
    decision = _a_decision(
        report,
        sequence=sequence,
        action=RepAction.APPROVED,
        settled=settled,
        email_edited=edited_email is not None,
        rep_words=rep_words,
        rep_minutes=rep_minutes,
        at=at,
    )
    if decision.outcome_changed or decision.amount_changed:
        decision = decision.model_copy(update={"action": RepAction.APPROVED_WITH_OVERRIDE})

    return ReviewOutcome(
        report=report.model_copy(
            update={
                "state": ReportState.APPROVED,
                "decided": settled,
                "decisions_taken": sequence + 1,
                "drafted_email": _the_email_that_stands(
                    report,
                    edited_email,
                    settled=settled,
                ),
                "reviews": (
                    *report.reviews,
                    _review_entry(
                        report,
                        decision=decision,
                        settled=settled,
                        edited_email=edited_email,
                        rep_words=rep_words,
                        policy=policy,
                    ),
                ),
            }
        ),
        decision=decision,
    )


def send_back(
    report: Report,
    *,
    feedback: str,
    rep_minutes: int = 0,
    at: UtcDatetime,
) -> ReviewOutcome:
    """Send a report back with a note saying what is wrong (FR-2.8, FR-R.1)."""
    if report.state is ReportState.APPROVED:
        raise ConflictError("This report has already been approved and cannot be sent back.")

    sequence = report.decisions_taken

    advised = Proposal(outcome=report.recommendation, amount_usd=report.amount_usd)
    decision = _a_decision(
        report,
        sequence=sequence,
        action=RepAction.SENT_BACK,
        settled=advised,
        email_edited=False,
        rep_words=feedback,
        rep_minutes=rep_minutes,
        at=at,
    )

    return ReviewOutcome(
        report=report.model_copy(
            update={
                "state": ReportState.CHANGES_REQUESTED,
                "decisions_taken": sequence + 1,
                "reviews": (
                    *report.reviews,
                    _review_entry(
                        report,
                        decision=decision,
                        settled=advised,
                        edited_email=None,
                        rep_words=feedback,
                        policy=None,
                    ),
                ),
            }
        ),
        decision=decision,
    )


def _already_approved(
    report: Report, *, settled: Proposal, edited_email: EmailWording | None
) -> ReviewOutcome:
    """Answer an approval of a report that has already been approved."""
    if report.decided != settled or edited_email is not None:
        raise ConflictError(
            "This report has already been approved, and this differs from what was approved."
        )
    return ReviewOutcome(report=report, decision=None)


def _a_decision(
    report: Report,
    *,
    sequence: int,
    action: RepAction,
    settled: Proposal,
    email_edited: bool,
    rep_words: str | None,
    rep_minutes: int,
    at: UtcDatetime,
) -> DecisionRecord:
    """Write down one review action (FR-C.1)."""
    return DecisionRecord(
        decision_id=_decision_id(report, sequence=sequence),
        case_id=report.case_id,
        stage=report.stage,
        report_version=report.version,
        action=action,
        recommended=Proposal(outcome=report.recommendation, amount_usd=report.amount_usd),
        decided=settled,
        email_edited=email_edited,
        stated_confidence=report.confidence,
        carrier=report.carrier,
        defect_type=report.defect_type,
        damage_type=report.damage_type,
        order_value_usd=report.order_value_usd,
        rep_minutes=rep_minutes,
        rep_words=rep_words,
        decided_by=None,
        decided_at=at,
    )


def _decision_id(report: Report, *, sequence: int) -> str:
    """Name one decision, the same way every time."""
    return f"DEC-{report.case_id}-{sequence:02d}"


def _review_entry(
    report: Report,
    *,
    decision: DecisionRecord,
    settled: Proposal,
    edited_email: EmailWording | None,
    rep_words: str | None,
    policy: Policy | None,
) -> ReportReview:
    """Keep what the representative decided as fields a UI can render (NFR-3)."""
    return ReportReview(
        review_number=report.decisions_taken + 1,
        action=decision.action,
        recommended=decision.recommended,
        decided=settled,
        edited_email=edited_email,
        rep_words=rep_words,
        over_the_cap_by=_over_the_cap_by(settled, policy=policy),
    )


def _over_the_cap_by(settled: Proposal, *, policy: Policy | None) -> Decimal | None:
    """How far a representative's own figure exceeds the most the system may recommend."""
    if policy is None or settled.amount_usd is None:
        return None
    over_by = settled.amount_usd - policy.reimbursement_cap_usd
    return over_by if over_by > 0 else None


def _the_email_that_stands(
    report: Report,
    edited_email: EmailWording | None,
    *,
    settled: Proposal,
) -> DraftedEmail | None:
    """The merchant's email as it stands after an approval."""
    if report.drafted_email is None:
        return None
    email = (
        report.drafted_email
        if edited_email is None
        else report.drafted_email.model_copy(
            update={"subject": edited_email.subject, "body": edited_email.body}
        )
    )
    if (
        settled.outcome is not None
        and settled.outcome.is_approval
        and settled.amount_usd is not None
    ):
        return email.with_approved_amount(
            settled.amount_usd,
            previous_amount_usd=report.amount_usd,
        )
    return email
