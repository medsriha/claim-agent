"""The write-up a support representative gets when a claim cannot be processed (FR-0.4).

When the pre-flight checks stop a claim, two people need to be told and they need
different things. The merchant needs an explanation they can act on, which is the
email. The representative needs to see the decision itself: which reasons stopped
the claim, what each of the four checks found, the facts gathered along the way, and
the exact wording that would go to the merchant if they approve it (FR-2.7).

This file builds that second thing, and the email is folded into it. There is no AI
anywhere in either — a claim we cannot process has to cost almost nothing (NFR-8),
and the same claim has to produce the same write-up every time (FR-0.6).

Two decisions are worth knowing before reading it. The write-up carries all four
check results, not only the failures, so a representative can see that the insurance
check ran and passed rather than having to infer it from silence (NFR-3). And it
mentions no money at all: the pre-flight screen recommends nothing, so there is no
amount for it to name.
"""

from __future__ import annotations

from collections.abc import Sequence

from claim_agent.domain.models import Case, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.email import draft_terminal_email
from claim_agent.preflight.models import ClaimContext, GateResult, TerminalReport


def build_terminal_report(
    case: Case,
    reasons: Sequence[TerminalReason],
    gates: Sequence[GateResult],
    context: ClaimContext,
    policy: Policy,
) -> TerminalReport:
    """Write up a stopped claim for the representative who has to approve closing it (FR-0.4).

    Gathers what the checks decided, turns each failed check into one plain sentence,
    and drafts the merchant's email to go with it. Nothing is sent and nothing is
    closed here: the result is something to read and approve.

    An insured claim is the one that comes out differently. Being insured is not
    something we write to a merchant about — those claims are routed out to the
    insurance process instead (FR-0.2) — so it is left out of the email and the
    write-up is marked as needing representative clarification. Any insured claim therefore
    carries no email at all, even when another gate also failed: clarification is the single
    next action, and no merchant wording should be generated for it.

    Args:
        case: The claim's support case, which names the merchant and the case id.
        reasons: Every reason the claim was stopped, already de-duplicated, insured
            first when it applies. The first reason a merchant can be told about
            names the email's subject line.
        gates: All four eligibility check results, passed and failed alike. The failed
            ones become the summary a representative reads; all four are kept.
        context: The facts worked out about the claim up front — what the order was
            worth, how many days passed, what a representative corrected for this
            merchant before (FR-0.5). Passed through untouched.
        policy: The claim policy, so the age limit quoted to the merchant is the one
            actually in force (FR-0.7).

    Returns:
        The write-up, marked as needing a representative's approval. Its summary holds
        one sentence for each check that failed, in the order the checks were handed
        over; a claim stopped by two checks therefore has two sentences. The drafted
        email is absent whenever the claim requires representative clarification.

    Raises:
        ValueError: if `reasons` is empty. A claim stopped for nothing anyone can name
            is a mistake in our own code, and it has to stop here rather than reach a
            representative as a blank explanation.
    """
    if not reasons:
        raise ValueError("A stopped claim needs at least one reason to write up.")

    insured = TerminalReason.SHIPMENT_INSURED in reasons
    # What is left once being insured is taken out: the reasons a merchant can
    # actually be written to about. Representative clarification takes precedence,
    # so an insured claim gets no email even when this tuple is not empty.
    tellable = tuple(reason for reason in reasons if reason is not TerminalReason.SHIPMENT_INSURED)

    return TerminalReport(
        case_id=case.case_id,
        account_name=case.account_name,
        user_id=case.user_id,
        reasons=tuple(reasons),
        findings=tuple(gate.explanation for gate in gates if not gate.passed),
        gates=tuple(gates),
        context=context,
        drafted_email=(
            draft_terminal_email(case, tellable, gates, context, policy)
            if tellable and not insured
            else None
        ),
        requires_rep_clarification=insured,
    )
