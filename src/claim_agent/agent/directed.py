from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.email import finish_email
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.investigate import ClaimFindings
from claim_agent.agent.ledger import RunLedger, StepKind
from claim_agent.agent.prompts import PROMPT_VERSION
from claim_agent.agent.schemas import DamagedItem, InvestigationConclusion
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import DraftedEmail, Invoice
from claim_agent.domain.outcome import Recommendation, decide_outcome
from claim_agent.domain.reimbursement import CENTS, AmountDerivation, review_recommended_amount
from claim_agent.errors import ModelOutputRejectedError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy

logger = get_logger(__name__)


_NOT_REVIEWED = (
    "Not reviewed: the representative directed payment before this was investigated, so "
    "nothing was established about it."
)

_APPROVAL_SUBJECT = "Your damage claim has been approved"
_APPROVAL_BODY = (
    "We have reviewed your damage claim for {products} and approved it. The approved amount "
    "will be reimbursed to your account."
)


class DirectedPayment(BaseModel):
    """A representative's instruction to pay, with what the model supplied to carry it out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    email_subject: str | None = None
    email_body: str | None = None
    amount_usd: str | None = None
    """The figure the representative named, as written, or `None` to price from the invoice."""


async def approve_as_directed(
    *,
    lines: Sequence[ClaimLine],
    directed: DirectedPayment,
    invoice: Invoice | None,
    policy: Policy,
    contact_email: str | None,
    model: str,
    events: EventStream,
    evidence: Sequence[EvidenceFinding] = (),
    assessments: Sequence[Assessment] = (),
    concerns: Sequence[str] = (),
    earlier_amount: AmountDerivation | None = None,
) -> ClaimFindings:
    """Pay a claim because a representative said to, without investigating it again."""
    budget = RunBudget(policy)
    ledger = RunLedger()
    products = _named(lines)

    await events.emit(
        EventKind.INVESTIGATION_STARTED,
        f"Pricing {products} as the representative directed, without another review of "
        "the evidence.",
        products=str(len(lines)),
    )

    amount = _the_figure(
        lines, directed=directed, earlier=earlier_amount, invoice=invoice, policy=policy
    )
    ledger.record(
        kind=StepKind.REASONING,
        name="price_as_directed",
        asked="What should be paid, now that the representative has directed payment?",
        observed=f"{amount.reasoning} Proposed ${amount.proposed_usd}; recommending ${amount.amount_usd}.",
        succeeded=amount.is_payable,
        reference=amount.priced_from,
    )

    found = _the_evidence_as_it_stands(evidence)
    decision = decide_outcome(
        Recommendation.APPROVE,
        evidence=found,
        assessments=assessments,
        lines=lines,
        amount=amount,
        policy=policy,
        directed_by_representative=True,
    )
    conclusion = _the_conclusion(lines, directed=directed, amount=amount)

    drafted, refused = _the_approval_email(
        conclusion,
        lines=lines,
        recommendation=decision.recommendation,
        amount=amount,
        contact_email=contact_email,
    )

    findings = ClaimFindings(
        lines=tuple(lines),
        evidence=found,
        assessments=tuple(assessments),
        outcome=decision,
        amount=amount,
        concerns=tuple(dict.fromkeys((*concerns, *refused))),
        drafted_email=drafted,
        ledger=ledger.entries(),
        budget=budget.snapshot(),
        conclusion=conclusion,
        requested_details=(),
        prompt_version=PROMPT_VERSION,
        model=model,
    )

    logger.info(
        "claim_paid_as_directed",
        products=len(lines),
        recommendation=decision.recommendation.value,
        amount_usd=str(amount.amount_usd),
        payable=amount.is_payable,
    )
    await events.emit(
        EventKind.INVESTIGATION_FINISHED,
        what_pricing_produced(findings),
        recommendation=decision.recommendation.value,
    )
    return findings


def what_pricing_produced(findings: ClaimFindings) -> str:
    """One sentence saying what came of the instruction, for the representative."""
    if findings.outcome.recommendation.is_approval:
        return (
            f"Priced at ${findings.amount.amount_usd.quantize(CENTS)} from the invoice and "
            "approved as you directed; the approval email is drafted above."
        )
    return (
        "Nothing on this claim could be priced from the invoice, so there is no figure to "
        "approve yet. Tell me the amount to pay and I will approve it at that; the approval "
        "email is drafted above for you to adjust."
    )


def _the_figure(
    lines: Sequence[ClaimLine],
    *,
    directed: DirectedPayment,
    earlier: AmountDerivation | None,
    invoice: Invoice | None,
    policy: Policy,
) -> AmountDerivation:
    """Settle what is paid, from the representative, the earlier report, or the invoice."""
    damaged = tuple(
        ClaimedProduct(name=line.product_name, quantity=line.claimed.quantity, sku=line.sku)
        for line in lines
    )

    if directed.amount_usd is not None:
        try:
            return review_recommended_amount(
                directed.amount_usd,
                reasoning="The representative named this figure.",
                damaged=damaged,
                invoice=invoice,
                policy=policy,
            )
        except ValueError as unreadable:
            logger.warning(
                "directed_amount_unreadable", proposed=directed.amount_usd, reason=str(unreadable)
            )

    if earlier is not None and earlier.proposed_usd > 0:
        return review_recommended_amount(
            str(earlier.proposed_usd),
            reasoning=(
                "The investigation's own figure for the damage, which the representative "
                "has directed be paid."
            ),
            damaged=damaged,
            invoice=invoice,
            policy=policy,
        )

    priced = review_recommended_amount(
        "0", reasoning="", damaged=damaged, invoice=invoice, policy=policy
    )
    return review_recommended_amount(
        str(priced.items_total_usd),
        reasoning=(
            "What the damaged products cost on the invoice, because the representative "
            "directed payment and named no figure."
            if priced.components
            else "The damaged products could not be priced from the invoice, and the "
            "representative named no figure."
        ),
        damaged=damaged,
        invoice=invoice,
        policy=policy,
    )


def _the_evidence_as_it_stands(
    evidence: Sequence[EvidenceFinding],
) -> tuple[EvidenceFinding, ...]:
    """Carry every finding forward, and say plainly which pieces were never looked at."""
    found = {finding.kind: finding for finding in evidence}
    return tuple(found.get(kind, _not_reviewed(kind)) for kind in REQUIRED_EVIDENCE)


def _not_reviewed(kind: EvidenceKind) -> EvidenceFinding:
    """Record that a piece of evidence was never reviewed, rather than that it was absent."""
    return EvidenceFinding(kind=kind, state=EvidenceState.MISSING, observed=_NOT_REVIEWED)


def _the_conclusion(
    lines: Sequence[ClaimLine], *, directed: DirectedPayment, amount: AmountDerivation
) -> InvestigationConclusion:
    """Write the instruction up in the form an investigation's answer takes."""
    return InvestigationConclusion(
        evidence=(),
        damaged_items=tuple(
            DamagedItem(
                product_name=line.product_name, quantity=line.claimed.quantity, sku=line.sku
            )
            for line in lines
        ),
        recommendation=Recommendation.APPROVE,
        reasoning=(
            "A representative directed that this claim be paid, so it was priced without "
            f"another review of the evidence. {amount.reasoning}"
        ),
        recommended_amount_usd=str(amount.proposed_usd),
        amount_reasoning=amount.reasoning,
        email_subject=directed.email_subject,
        email_body=directed.email_body,
    )


def _the_approval_email(
    conclusion: InvestigationConclusion,
    *,
    lines: Sequence[ClaimLine],
    recommendation: Recommendation,
    amount: AmountDerivation,
    contact_email: str | None,
) -> tuple[DraftedEmail, tuple[str, ...]]:
    """Finish the model's approval wording, or fall back to plain wording of our own."""
    try:
        return (
            finish_email(
                conclusion,
                recommendation=recommendation,
                amount=amount,
                contact_email=contact_email,
            ),
            (),
        )
    except ModelOutputRejectedError as refused:
        logger.warning("directed_approval_email_replaced", reason=refused.message)
        plain = conclusion.model_copy(
            update={
                "email_subject": _APPROVAL_SUBJECT,
                "email_body": _APPROVAL_BODY.format(products=_named(lines)),
            }
        )
        return (
            finish_email(
                plain, recommendation=recommendation, amount=amount, contact_email=contact_email
            ),
            (f"{refused.message} A plain approval email was used instead.",),
        )


def _named(lines: Sequence[ClaimLine]) -> str:
    """The products being paid for, written out for a sentence."""
    return ", ".join(line.product_name for line in lines) or "this claim"
