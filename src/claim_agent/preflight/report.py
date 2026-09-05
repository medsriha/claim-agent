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
    """Build the representative report and optional email for a stopped claim."""
    if not reasons:
        raise ValueError("A stopped claim needs at least one reason to write up.")

    insured = TerminalReason.SHIPMENT_INSURED in reasons
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
