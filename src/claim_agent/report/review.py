"""The two things a representative may do to a report, and the record each one leaves.

A report is a proposal. This is where a person accepts one or sends it back, and where what they
chose is written down so it can be counted, audited, and carried forward (FR-2.8, FR-C.1).

**Approving is the only way out.** A report can go back and forth as often as a representative
likes, and no time limit, level of confidence or number of rounds ever approves one for them
(FR-2.9). Once approved it is final: it cannot be reopened, sent back, or approved again
differently.

**Recording a decision is not carrying it out.** Nothing here sends an email or moves money. The
stage that would act on an approval lives in `claim_agent.execution` and does not exist, so an
approval today stops at being recorded (FR-3.1).

Pure: no clock, no store, no network. The moment is handed in, so deciding the same report the
same way twice produces the same record twice.
"""

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
    """What one review action produced: the report as it now stands, and the record of the act.

    The two are deliberately separate. The report is what a representative sees next; the record
    is what happened, and it survives even if acting on it later fails (FR-3.6, FR-C.1).

    `decision` is `None` only when nothing happened — an approval repeated on a report already
    approved the same way, where the record was written the first time and re-writing it would
    count one event twice.
    """

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
    """Accept a report, as it stands or after changing it (FR-2.8, FR-2.9, FR-C.1).

    Args:
        report: The report being decided on.
        decided_outcome: What the representative settled on, if they changed it. `None` leaves the
            recommendation as it stands.
        decided_amount_usd: What they settled on paying, if they changed it. `None` leaves the
            figure as it stands. **A figure over the cap is accepted**, recorded as it was made,
            and flagged in the report — the cap limits what the system may recommend, and no
            requirement says a person may not exceed it. Refusing would throw away a decision
            somebody made, which FR-C.4 is explicit is the worse loss (FR-1.20, FR-R.8).
        edited_email: The merchant's email as they reworded it, or `None` if they left it alone.
            Wording only: changing what the email *tells* a merchant is substance, and FR-2.8
            draws that line by sending substance back as feedback instead.
        rep_words: Anything they said, in their own words.
        rep_minutes: How long the review took, in whole minutes. Nothing measures this and nothing
            in this system ever has, so it arrives as whatever the caller says and is 0 by default.
        policy: Read for the most that may be recommended on one claim (FR-0.7).
        at: When the decision was taken.

    Returns:
        The approved report and the record of the approval. Approving a report that is already
        approved **in exactly this way** returns it unchanged with no second record, so a
        double-click or a retry after a slow reply leaves one decision rather than two
        (FR-C.4, FR-3.5).

    Raises:
        ConflictError: The report is already approved and this approval differs from the one that
            was made. A decision a person took is not something a later request may quietly
            replace.
    """
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
        # Read off the record rather than compared again here. Those two properties are the
        # comparison FR-C.2 is built on, and a second copy of it could disagree with the first.
        decision = decision.model_copy(update={"action": RepAction.APPROVED_WITH_OVERRIDE})

    return ReviewOutcome(
        report=report.model_copy(
            update={
                "state": ReportState.APPROVED,
                "decided": settled,
                "decisions_taken": sequence + 1,
                "drafted_email": _the_email_that_stands(report, edited_email),
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
    """Send a report back with a note saying what is wrong (FR-2.8, FR-R.1).

    The note is recorded and the report is parked. **Nothing picks it up**: the stage that would
    rework a report around what a representative said is not built, so a report sent back waits
    for somebody to approve it or for that stage to exist. DESIGN.md says so rather than this
    pretending otherwise.

    Args:
        report: The report being sent back.
        feedback: What is wrong or missing, in the representative's own words. This is the whole
            input to the reworking that will one day happen, so it is kept exactly as written.
        rep_minutes: How long the review took, in whole minutes.
        at: When the decision was taken.

    Returns:
        The parked report and the record of the note. **Two notes on one report are two
        decisions**, and both are recorded — a representative who says one thing and then another
        has decided twice, and collapsing them would lose the first (FR-C.1).

    Raises:
        ConflictError: The report has already been approved. An approval is final, and un-doing
            one would undo something FR-3.1 says releases execution.
    """
    if report.state is ReportState.APPROVED:
        raise ConflictError("This report has already been approved and cannot be sent back.")

    sequence = report.decisions_taken
    # Nothing was chosen, so what was decided is what was advised. The action is what says the
    # report was not usable as it arrived, not a difference between these two.
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
    """Answer an approval of a report that has already been approved.

    The same approval again is a double-click or a retry after a slow reply, and it must leave one
    decision rather than two — every figure worked out from the record would be wrong otherwise
    (FR-C.4, FR-3.5). A *different* approval is somebody trying to replace a decision a person
    already took, which is refused rather than quietly applied.

    A rewording arriving after the approval counts as different. The wording is what was approved,
    so changing it afterwards changes what was agreed.
    """
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
    """Write down one review action (FR-C.1).

    `decided_by` is always empty. There is no sign-in anywhere in this system, so the record
    cannot say which representative decided, and FR-C.1 is explicit that the field must exist and
    be left empty rather than filled with a guess.
    """
    return DecisionRecord(
        decision_id=_decision_id(report, sequence=sequence),
        case_id=report.case_id,
        claim_line_id=report.claim_line_id,
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
    """Name one decision, the same way every time.

    Worked out from what it was about and which decision on it this is, rather than handed out
    fresh, so repeating a decision writes over its own record instead of adding a second
    (FR-C.4). The sequence is what keeps two *different* notes on one report from sharing a name
    and one of them being lost.

    A claim the quick checks stopped has no product to name, so its own identifier is used.
    """
    about = report.claim_line_id or report.case_id
    return f"DEC-{about}-{sequence:02d}"


def _review_entry(
    report: Report,
    *,
    decision: DecisionRecord,
    settled: Proposal,
    edited_email: EmailWording | None,
    rep_words: str | None,
    policy: Policy | None,
) -> ReportReview:
    """Keep what the representative decided as fields a UI can render (NFR-3).

    `policy` is `None` where no figure was chosen — sending a report back settles no amount, so
    there is nothing that could be over the cap.
    """
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
    """How far a representative's own figure exceeds the most the system may recommend.

    `None` when it does not, and `None` when no figure was settled at all. The difference is
    reported rather than the decision being refused: the cap limits what the system recommends,
    and a person deciding to pay more is a decision to record rather than one to throw away
    (FR-1.20, FR-R.8, FR-C.4).
    """
    if policy is None or settled.amount_usd is None:
        return None
    over_by = settled.amount_usd - policy.reimbursement_cap_usd
    return over_by if over_by > 0 else None


def _the_email_that_stands(
    report: Report, edited_email: EmailWording | None
) -> DraftedEmail | None:
    """The merchant's email as it stands after an approval.

    A rewording replaces the wording and never the recipient: who hears about a claim comes from
    the claim's own contact address and is not a representative's to change (FR-3.2). A report
    with nothing to send stays with nothing to send — there is no address to reword an email to.
    """
    if edited_email is None or report.drafted_email is None:
        return report.drafted_email
    return report.drafted_email.model_copy(
        update={"subject": edited_email.subject, "body": edited_email.body}
    )
