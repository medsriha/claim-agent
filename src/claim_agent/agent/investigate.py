"""Layer 1b — look into one whole claim and hand a representative a decision (FR-1b.1)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import BudgetLimit, BudgetSnapshot, RunBudget
from claim_agent.agent.email import finish_email, name_what_is_missing
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import LedgerEntry, RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.loop import LoopOutcome, run_agent_pass
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import build_investigation_messages
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.agent.tools import investigation_tools
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, Assessment
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    SHARED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import Attachment, DraftedEmail, Invoice
from claim_agent.domain.outcome import OutcomeDecision, Recommendation, decide_outcome
from claim_agent.domain.reimbursement import AmountDerivation, review_recommended_amount
from claim_agent.errors import ModelOutputRejectedError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet

logger = get_logger(__name__)

# Any answer built on the investigation's own form.
AnyConclusion = TypeVar("AnyConclusion", bound=InvestigationConclusion)
# What the run is asked once it has stopped looking at things.
CLOSING_REQUEST = (
    "Now give your conclusion for this claim: what each of the four pieces of evidence "
    "showed, your answers to the four questions if the evidence was all there, every "
    "product that should be paid for, your next action, and — only when that action "
    "addresses the merchant — the email draft."
)
# Each recommendation as a representative would say it, for the message on a screen.
_RECOMMENDATION_IN_WORDS: dict[Recommendation, str] = {
    Recommendation.APPROVE: "pay this claim",
    Recommendation.APPROVE_HIGH_VALUE: "pay this claim, and look again at what it cost",
    Recommendation.REQUEST_INFO: "go back to the merchant",
    Recommendation.REQUEST_REP_CLARIFICATION: "ask the representative for clarification",
}
# What is recorded for a piece of evidence nobody reported on.
_NOTHING_ESTABLISHED = "Nothing was established about this piece of evidence."


class ClaimFindings(BaseModel):
    """Everything one claim's investigation established, ready to be reported on (FR-1b.1).

    `lines` is every damaged product the claim covers, and there is one `outcome`, one
    `amount` and one `drafted_email` across all of them (FR-1b.3). What each product
    contributed to the figure is in `amount.components`.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    lines: tuple[ClaimLine, ...]
    evidence: tuple[EvidenceFinding, ...]
    assessments: tuple[Assessment, ...]
    outcome: OutcomeDecision
    amount: AmountDerivation
    concerns: tuple[str, ...]
    drafted_email: DraftedEmail | None
    ledger: tuple[LedgerEntry, ...]
    budget: BudgetSnapshot
    conclusion: InvestigationConclusion | None
    requested_details: tuple[str, ...] = ()

    @property
    def confidence(self) -> float | None:
        """No subjective confidence score is requested or shown for agent conclusions."""
        return None


async def investigate_claim_lines(
    *,
    lines: Sequence[ClaimLine],
    record: CaseRecord,
    context: ClaimContext,
    attachments: Sequence[Attachment],
    invoice: Invoice | None,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    cache: ObservationCache,
    events: EventStream,
    policy: Policy,
    shared_evidence: Sequence[EvidenceFinding] = (),
    precedent: PrecedentSet | None = None,
) -> ClaimFindings:
    """Investigate one claim and produce everything a representative needs (FR-1b.1)."""
    case = record.case
    # One budget and one record for the run, built here rather than taken as arguments, so a
    # claim can never end up sharing an allowance with the triage pass that preceded it
    # (FR-1.3).
    budget = RunBudget(policy)
    ledger = RunLedger()

    await events.emit(
        EventKind.INVESTIGATION_STARTED,
        f"Looking into this claim: {_named(lines)}.",
        products=str(len(lines)),
    )

    outcome = await run_agent_pass(
        opening_messages=build_investigation_messages(
            case=case,
            order=record.order,
            attachments=attachments,
            context=context,
            claim_lines=lines,
            shared_evidence=shared_evidence,
            precedent=precedent,
        ),
        tools=investigation_tools(
            case_id=case.case_id,
            shipment_id=case.shipment_id,
            user_id=case.user_id,
            case=case,
            shipment=record.shipment,
            evidence=evidence,
            fetcher=fetcher,
            model=structured,
            cache=cache,
            budget=budget,
            ledger=ledger,
            events=events,
            policy=policy,
        ),
        concludes_with=InvestigationConclusion,
        closing_request=CLOSING_REQUEST,
        chat=chat,
        structured=structured,
        budget=budget,
        ledger=ledger,
        events=events,
    )

    investigated = settle_conclusion(
        outcome,
        lines=lines,
        shared_evidence=shared_evidence,
        invoice=invoice,
        policy=policy,
        contact_email=case.contact_email,
    )

    logger.info(
        "claim_investigated",
        case_id=case.case_id,
        products=len(lines),
        recommendation=investigated.outcome.recommendation.value,
        recommended_by_agent=investigated.outcome.recommended_by_agent.value,
        gave_up=outcome.gave_up,
    )
    await events.emit(
        EventKind.INVESTIGATION_FINISHED,
        "Finished with this claim. The recommendation is to "
        f"{_RECOMMENDATION_IN_WORDS[investigated.outcome.recommendation]}.",
        recommendation=investigated.outcome.recommendation.value,
    )
    return investigated


def settle_conclusion(
    outcome: LoopOutcome[AnyConclusion],
    *,
    lines: Sequence[ClaimLine],
    shared_evidence: Sequence[EvidenceFinding],
    invoice: Invoice | None,
    policy: Policy,
    contact_email: str | None,
    directed_by_representative: bool = False,
) -> ClaimFindings:
    """Turn what the run came back with into the write-up a representative reads."""
    if outcome.answer is None:
        return _a_run_that_gave_up(
            outcome, lines=lines, shared=shared_evidence, invoice=invoice, policy=policy
        )

    conclusion = outcome.answer
    evidence = _what_the_evidence_shows(conclusion.evidence, shared_evidence)
    assessments = _questions_that_were_answered(conclusion.assessments)
    amount = _amount_it_recommends(conclusion, invoice=invoice, policy=policy)
    concerns = _concerns(conclusion, shared_evidence)
    requested_details = _requested_details(conclusion, evidence)

    decision = decide_outcome(
        conclusion.recommendation,
        evidence=evidence,
        assessments=assessments,
        lines=lines,
        amount=amount,
        policy=policy,
        requested_details=requested_details,
        directed_by_representative=directed_by_representative,
    )

    if decision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION:
        # This action is entirely internal. No merchant wording is generated or surfaced
        # while the representative still has to resolve what is wrong or ambiguous.
        drafted = None
    else:
        try:
            drafted = finish_email(
                conclusion,
                recommendation=decision.recommendation,
                amount=amount,
                contact_email=contact_email,
                requested_details=requested_details,
            )
        except ModelOutputRejectedError as refused:
            # Unsafe or incomplete merchant wording becomes a clarification request. The
            # report keeps the investigation's conclusion and explains why no email was made.
            logger.warning(
                "drafted_email_refused",
                recommendation=decision.recommendation.value,
            )
            return ClaimFindings(
                lines=tuple(lines),
                evidence=evidence,
                assessments=assessments,
                outcome=_hand_it_to_a_person(
                    evidence=evidence,
                    assessments=assessments,
                    lines=lines,
                    amount=amount,
                    policy=policy,
                ),
                amount=amount,
                concerns=_also(concerns, refused.message),
                drafted_email=None,
                ledger=outcome.ledger,
                budget=outcome.budget,
                conclusion=conclusion,
                requested_details=(),
            )

    return ClaimFindings(
        lines=tuple(lines),
        evidence=evidence,
        assessments=assessments,
        outcome=decision,
        amount=amount,
        concerns=concerns,
        drafted_email=drafted,
        ledger=outcome.ledger,
        budget=outcome.budget,
        conclusion=conclusion,
        requested_details=(
            requested_details if decision.recommendation is Recommendation.REQUEST_INFO else ()
        ),
    )


def _requested_details(
    conclusion: InvestigationConclusion, evidence: Sequence[EvidenceFinding]
) -> tuple[str, ...]:
    """Merge standard evidence requests with the agent's other merchant-fillable gaps."""
    named = (*name_what_is_missing(evidence), *conclusion.requested_details)
    return tuple(dict.fromkeys(detail.strip() for detail in named if detail.strip()))


def _a_run_that_gave_up(
    outcome: LoopOutcome[AnyConclusion],
    *,
    lines: Sequence[ClaimLine],
    shared: Sequence[EvidenceFinding],
    invoice: Invoice | None,
    policy: Policy,
) -> ClaimFindings:
    """Write up a run that stopped before it could conclude (FR-1.16, NFR-4)."""
    evidence = _what_the_evidence_shows((), shared)
    amount = _no_amount_at_all(invoice=invoice, policy=policy)
    return ClaimFindings(
        lines=tuple(lines),
        evidence=evidence,
        assessments=(),
        outcome=_hand_it_to_a_person(
            evidence=evidence,
            assessments=(),
            lines=lines,
            amount=amount,
            policy=policy,
            budget_exhausted=_ran_out_of_steps(outcome),
        ),
        amount=amount,
        concerns=_also((), outcome.reason),
        drafted_email=None,
        ledger=outcome.ledger,
        budget=outcome.budget,
        conclusion=None,
    )


def _amount_it_recommends(
    conclusion: InvestigationConclusion, *, invoice: Invoice | None, policy: Policy
) -> AmountDerivation:
    """Read the figure the investigation recommends, and hold it to the cap (FR-1.21)."""
    proposed = conclusion.recommended_amount_usd
    if proposed is None:
        return _no_amount_at_all(invoice=invoice, policy=policy)

    try:
        return review_recommended_amount(
            proposed,
            reasoning=conclusion.amount_reasoning or "",
            damaged=_damaged_products(conclusion),
            invoice=invoice,
            policy=policy,
        )
    except ValueError as refused:
        logger.warning("recommended_amount_unreadable", proposed=proposed, reason=str(refused))
        return _no_amount_at_all(invoice=invoice, policy=policy)


def _no_amount_at_all(*, invoice: Invoice | None, policy: Policy) -> AmountDerivation:
    """An amount of nothing, with the items still priced for context."""
    return review_recommended_amount(
        "0",
        reasoning="",
        damaged=(),
        invoice=invoice,
        policy=policy,
    )


def _hand_it_to_a_person(
    *,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    lines: Sequence[ClaimLine],
    amount: AmountDerivation,
    policy: Policy,
    budget_exhausted: bool = False,
) -> OutcomeDecision:
    """Settle a claim that has to go to a person, still through the ordinary rules."""
    return decide_outcome(
        Recommendation.REQUEST_REP_CLARIFICATION,
        evidence=evidence,
        assessments=assessments,
        lines=lines,
        amount=amount,
        policy=policy,
        budget_exhausted=budget_exhausted,
    )


def _ran_out_of_steps(outcome: LoopOutcome[AnyConclusion]) -> bool:
    """Say whether the run stopped without concluding because its steps ran out (FR-1.16)."""
    return outcome.gave_up and BudgetLimit.STEPS in outcome.budget.limits_reached


def _named(lines: Sequence[ClaimLine]) -> str:
    """The claim's damaged products, written out for a message on a screen."""
    if not lines:
        return "no product could be established"
    return ", ".join(line.product_name for line in lines)


def _what_the_evidence_shows(
    reported: Sequence[EvidenceJudgement], shared: Sequence[EvidenceFinding]
) -> tuple[EvidenceFinding, ...]:
    """Merge what the claim settled once with what this run found about its own photographs."""
    this_run = {judgement.kind: _as_a_finding(judgement) for judgement in reported}
    settled_once = {finding.kind: finding for finding in shared if finding.kind in SHARED_EVIDENCE}
    found = {**this_run, **settled_once}
    return tuple(found.get(kind, _nothing_found_about(kind)) for kind in REQUIRED_EVIDENCE)


def _as_a_finding(judgement: EvidenceJudgement) -> EvidenceFinding:
    """Turn the form the model filled in about one piece of evidence into a finding."""
    return EvidenceFinding(
        kind=judgement.kind,
        state=judgement.state,
        observed=judgement.observed,
        attachment_id=judgement.attachment_id,
        problem=judgement.problem,
    )


def _nothing_found_about(kind: EvidenceKind) -> EvidenceFinding:
    """Record that one of the four pieces of evidence was never reported on."""
    return EvidenceFinding(kind=kind, state=EvidenceState.MISSING, observed=_NOTHING_ESTABLISHED)


def _questions_that_were_answered(
    judgements: Sequence[AssessmentJudgement],
) -> tuple[Assessment, ...]:
    """The four questions this run actually answered, in the fixed reporting order."""
    answered = {judgement.name: _as_an_assessment(judgement) for judgement in judgements}
    return tuple(answered[name] for name in REQUIRED_ASSESSMENTS if name in answered)


def _as_an_assessment(judgement: AssessmentJudgement) -> Assessment:
    """Turn the form the model filled in about one question into a judgement on the claim."""
    return Assessment(
        name=judgement.name,
        passed=judgement.passed,
        reasoning=judgement.reasoning,
        attachment_ids=judgement.attachment_ids,
    )


def _damaged_products(conclusion: InvestigationConclusion) -> tuple[ClaimedProduct, ...]:
    """The products the run says were damaged, in the shape the arithmetic prices."""
    return tuple(
        ClaimedProduct(name=item.product_name, quantity=item.quantity, sku=item.sku)
        for item in conclusion.damaged_items
    )


def _concerns(
    conclusion: InvestigationConclusion, shared: Sequence[EvidenceFinding]
) -> tuple[str, ...]:
    """Everything a reviewer should know that does not fit anywhere else (FR-2.5)."""
    return _also(
        conclusion.concerns,
        _the_ambiguity(conclusion),
        *_where_this_run_disagreed(conclusion, shared),
    )


def _the_ambiguity(conclusion: InvestigationConclusion) -> str | None:
    """Say what the run could not tell apart, or `None` if it could tell (FR-1.13)."""
    if not conclusion.is_ambiguous:
        return None
    if conclusion.ambiguity is None:
        return "The investigation could not tell which product on the order was damaged."
    return (
        "The investigation could not tell which product on the order was damaged: "
        f"{conclusion.ambiguity}"
    )


def _where_this_run_disagreed(
    conclusion: InvestigationConclusion, shared: Sequence[EvidenceFinding]
) -> tuple[str, ...]:
    """Name every piece of shared evidence this run read differently from the claim."""
    settled_once = {finding.kind: finding for finding in shared if finding.kind in SHARED_EVIDENCE}
    this_run = {judgement.kind: judgement for judgement in conclusion.evidence}
    return tuple(
        f"This run read the {kind.value.replace('_', ' ')} as "
        f"{this_run[kind].state.value} while the claim had settled it as "
        f"{settled_once[kind].state.value}. The claim's answer stands, so every product "
        "on it is judged the same way."
        for kind in REQUIRED_EVIDENCE
        if kind in settled_once
        and kind in this_run
        and this_run[kind].state is not settled_once[kind].state
    )


def _also(concerns: Sequence[str], *added: str | None) -> tuple[str, ...]:
    """Add to a list of concerns, keeping the order and dropping repeats."""
    kept = [*concerns, *(one for one in added if one)]
    return tuple(dict.fromkeys(kept))
