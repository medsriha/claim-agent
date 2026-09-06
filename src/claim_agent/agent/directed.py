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

# What a report says about a piece of evidence that was never looked at on this pass.
_NOT_REVIEWED = (
    "Not reviewed: the representative directed payment before this was investigated, so "
    "nothing was established about it."
)
# The email a merchant gets when the model supplied no usable approval wording.
_APPROVAL_SUBJECT = "Your damage claim has been approved"
_APPROVAL_BODY = (
    "We have reviewed your damage claim for {products} and approved it. The approved amount "
    "will be reimbursed to your account."
)


class DirectedPayment(BaseModel):
    """A representative's instruction to pay, with what the model supplied to carry it out.

    This is everything the model contributes to a directed payment: the approval email's
    wording and, when the representative named one, the figure they named. The figure is
    kept as the text the model wrote, because money is parsed exactly once, where it is
    priced (FR-1.20, FR-1.21).
    """

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
    """Pay a claim because a representative said to, without investigating it again.

    A representative who has read a report and told the agent to approve it has answered the
    only question that was open. Nothing about the evidence needs to be looked at again to
    carry that out: what is left is to settle the figure and write the email, and both of
    those are arithmetic and wording rather than judgement. So this does exactly that, with
    no model call and no tool — one invoice read, one figure, one email.

    The figure comes from the first of these that exists: the amount the representative
    named; the amount the investigation itself judged the damage to be worth, where a report
    had one and the rules withheld it; and otherwise what the damaged products cost on the
    invoice. Whichever it is, it is held to the cap where it is read (FR-1.20), and the
    email carries the figure that survived rather than any figure the model wrote (FR-1.21).

    Every rule that would have withheld the payment is evaluated and recorded as waived, so
    a payment a person directed and one the evidence earned never look the same (NFR-5).
    A directed payment with nothing payable is still refused, because there would be no
    figure to put in the email; the report then asks the representative what to pay.

    Args:
        lines: The products being paid for, matched against the order.
        directed: The instruction, as the model read it: email wording and any figure named.
        invoice: ShipBob's priced record of the shipment, or `None` when it could not be read.
        policy: Read for the reimbursement cap and the high-value figure (FR-0.7).
        contact_email: Who the approval email goes to, from the case.
        model: The name of the model that read the instruction, for the record on the report.
        events: Where progress is narrated for whoever is watching.
        evidence: What an earlier investigation established about the four pieces of
            evidence, carried forward unchanged. Empty for a claim nobody investigated.
        assessments: Its answers to the four questions, likewise carried forward.
        concerns: Its concerns, likewise.
        earlier_amount: The figure the earlier report worked out, if it worked one out.

    Returns:
        The claim's findings, approved with the figure and the email, or handed to the
        representative when nothing could be priced.
    """
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

    # The email is written whether or not a figure could be found. Where it could not, the
    # report asks the representative for one and keeps the draft, so they adjust wording
    # on their screen and answer with the figure rather than start again from nothing.
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
    """One sentence saying what came of the instruction, for the representative.

    The model's reply is written before anything is priced, so on its own it can only say
    what is about to happen. The outcome is added afterwards, by code, because code is the
    only thing that knows it.
    """
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
    """Write the instruction up in the form an investigation's answer takes.

    The report reads its summary and its email wording off a conclusion, so a directed
    payment gets one that says exactly what happened: nothing was judged, a person decided.
    """
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
    """Finish the model's approval wording, or fall back to plain wording of our own.

    A directed payment must not fail for want of an email: the representative has decided,
    and the email is the one thing left between that decision and the merchant. So where the
    model wrote no wording, or wrote a figure into it, the report says so as a concern and
    a short deterministic email is used instead. The figure is added by code, and only
    when there is one: a draft kept while the representative is asked for the figure has
    no amount line, and gains one when they approve at a figure.
    """
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
