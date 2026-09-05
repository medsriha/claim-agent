"""Investigating a whole claim: split it, look into each product, then check the total."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import LineInvestigation, investigate_line
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.precedent_context import precedent_for_line
from claim_agent.agent.triage import ClaimTriage, triage_claim
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.models import Case, Invoice
from claim_agent.domain.outcome import OutcomeDecision, OverrideReason, Recommendation
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet, PrecedentStore

logger = get_logger(__name__)


class ClaimInvestigation(BaseModel):
    """Everything an investigation established about one claim, product by product."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    triage: ClaimTriage
    lines: tuple[LineInvestigation, ...] = ()
    claim_concerns: tuple[str, ...] = ()
    recommended_total_usd: Decimal = Decimal("0.00")
    claim_cap_applied: bool = False


async def investigate_claim(
    *,
    record: CaseRecord,
    context: ClaimContext,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    events: EventStream,
    policy: Policy,
    cache: ObservationCache | None = None,
    precedent_store: PrecedentStore | None = None,
) -> ClaimInvestigation:
    """Investigate every damaged product on one claim (FR-1a.*, FR-1b.*)."""
    shared_cache = cache if cache is not None else ObservationCache()

    triage = await triage_claim(
        record=record,
        context=context,
        evidence=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        cache=shared_cache,
        budget=_a_budget_for_the_split(policy),
        ledger=_a_ledger_for_the_split(),
        events=events,
        policy=policy,
    )

    if triage.is_ambiguous or not triage.claim_lines:
        # Nothing may be investigated while it is unclear which products are being
        # claimed for. Guessing a split is silent and expensive; asking the party who
        # can settle it is neither (FR-1a.4).
        logger.info("claim_split_unsettled", case_id=triage.case_id, ambiguity=triage.ambiguity)
        return ClaimInvestigation(case_id=triage.case_id, triage=triage)

    invoice = await invoice_for_claim(record=record, evidence=evidence, cache=shared_cache)

    # Looked up before the products fan out: the store is a file on disk and reading it
    # blocks. It also means every run starts with its precedent already in hand, which is
    # what FR-S.6 asks for — precedent arrives with the claim, never fetched on a whim.
    precedent = _precedent_for_each(
        store=precedent_store, case=record.case, lines=triage.claim_lines, policy=policy
    )
    await _say_what_precedent_was_found(precedent, lines=triage.claim_lines, events=events)

    # Each product gets its own investigation, and they run together. Nothing is
    # shared between them but read-only facts: the same records, the same settled
    # evidence, and one memo of what has already been looked at.
    finished = await asyncio.gather(
        *(
            investigate_line(
                line=line,
                record=record,
                context=context,
                attachments=triage.attachments,
                invoice=invoice,
                evidence=evidence,
                fetcher=fetcher,
                chat=chat,
                structured=structured,
                cache=shared_cache,
                events=events,
                policy=policy,
                shared_evidence=triage.shared_evidence,
                siblings=tuple(other for other in triage.claim_lines if other is not line),
                precedent=precedent.get(line.claim_line_id),
            )
            for line in triage.claim_lines
        )
    )

    return await _check_the_claim_total(
        case_id=triage.case_id,
        triage=triage,
        lines=finished,
        events=events,
        policy=policy,
    )


def _precedent_for_each(
    *,
    store: PrecedentStore | None,
    case: Case,
    lines: Sequence[ClaimLine],
    policy: Policy,
) -> dict[str, PrecedentSet]:
    """Look up the closed claims most like each product, before any of them is investigated."""
    if store is None:
        return {}
    return {
        line.claim_line_id: precedent_for_line(
            store=store,
            case=case,
            line=line,
            policy=policy,
            shared_evidence=(),
        )
        for line in lines
    }


async def _say_what_precedent_was_found(
    precedent: Mapping[str, PrecedentSet],
    *,
    lines: Sequence[ClaimLine],
    events: EventStream,
) -> None:
    """Tell whoever is watching what comparable past claims were found, product by product."""
    for line in lines:
        found = precedent.get(line.claim_line_id)

        if found is None:
            summary = "No past claims were looked up for this product."
            outcome = "not_looked_up"
            count = 0
        elif not found.was_read:
            summary = (
                "Past claims could not be read for this product, so nothing is known "
                "about how claims like it were handled."
            )
            outcome = "unreadable"
            count = 0
        elif not found.retrieved:
            summary = "No past claim close enough to this product was found."
            outcome = "none_alike"
            count = 0
        else:
            count = len(found.retrieved)
            summary = (
                f"Found {count} past claim(s) like this product, out of "
                f"{found.considered} looked at."
            )
            outcome = "found"

        await events.emit(
            EventKind.PRECEDENT_GATHERED,
            summary,
            claim_line_id=line.claim_line_id,
            outcome=outcome,
            found=str(count),
        )


class ClaimCapVerdict(BaseModel):
    """What the cap makes of a whole claim, once each product has been judged alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[LineInvestigation, ...]
    total_usd: Decimal
    applied: bool
    complaint: str | None = None


def apply_claim_cap(lines: Sequence[LineInvestigation], *, policy: Policy) -> ClaimCapVerdict:
    """Add up what is being recommended and apply the cap across the whole claim (FR-1.20)."""
    total = sum(
        (line.amount.amount_usd for line in lines if line.outcome.recommendation.is_approval),
        start=Decimal("0.00"),
    )

    if not (policy.cap_applies_to_whole_claim and total > policy.reimbursement_cap_usd):
        return ClaimCapVerdict(lines=tuple(lines), total_usd=total, applied=False)

    complaint = (
        f"The products recommended for payment come to {total} between them, over the "
        f"{policy.reimbursement_cap_usd} a claim may be reimbursed. Each was judged "
        "sound on its own evidence; what to pay across the claim is a decision for a "
        "representative."
    )
    return ClaimCapVerdict(
        lines=tuple(_held_back_by_the_claim_cap(line, complaint) for line in lines),
        total_usd=total,
        applied=True,
        complaint=complaint,
    )


async def _check_the_claim_total(
    *,
    case_id: str,
    triage: ClaimTriage,
    lines: Sequence[LineInvestigation],
    events: EventStream,
    policy: Policy,
) -> ClaimInvestigation:
    """Add up what is being recommended and apply the cap across the whole claim (FR-1.20)."""
    verdict = apply_claim_cap(lines, policy=policy)

    if not verdict.applied:
        return ClaimInvestigation(
            case_id=case_id,
            triage=triage,
            lines=verdict.lines,
            recommended_total_usd=verdict.total_usd,
        )

    complaint = verdict.complaint or ""
    total = verdict.total_usd
    logger.info(
        "claim_over_the_cap",
        case_id=case_id,
        recommended_total=str(total),
        cap=str(policy.reimbursement_cap_usd),
    )
    await events.emit(
        EventKind.LINE_FINISHED,
        complaint,
        outcome="claim_cap_exceeded",
        recommended_total=str(total),
    )

    return ClaimInvestigation(
        case_id=case_id,
        triage=triage,
        lines=tuple(_held_back_by_the_claim_cap(line, complaint) for line in lines),
        claim_concerns=(complaint,),
        recommended_total_usd=total,
        claim_cap_applied=True,
    )


def _held_back_by_the_claim_cap(line: LineInvestigation, complaint: str) -> LineInvestigation:
    """Turn one product's recommended payment into an representative clarification request, keeping
    everything else.
    """
    if not line.outcome.recommendation.is_approval:
        return line

    return line.model_copy(
        update={
            "outcome": OutcomeDecision(
                recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
                recommended_by_agent=line.outcome.recommended_by_agent,
                overrides=(*line.outcome.overrides, OverrideReason.CLAIM_CAP_EXCEEDED),
                explanation=complaint,
            ),
            "concerns": (*line.concerns, complaint),
            # The email said a figure would be paid. It no longer would be, and a draft
            # that promises money nobody has approved must not survive the change.
            "drafted_email": None,
        }
    )


async def invoice_for_claim(
    *, record: CaseRecord, evidence: EvidenceClient, cache: ObservationCache
) -> Invoice | None:
    """Fetch the priced invoice once for the whole claim, or come back with nothing."""
    shipment_id = record.case.shipment_id
    user_id = record.case.user_id
    if shipment_id is None or user_id is None:
        return None

    async def priced() -> Invoice | None:
        try:
            return await evidence.generate_invoice(shipment_id=shipment_id, user_id=user_id)
        except ClaimAgentError as failure:
            logger.warning(
                "claim_invoice_unavailable",
                case_id=record.case.case_id,
                shipment_id=shipment_id,
                failure=type(failure).__name__,
            )
            return None

    return await cache.get_or_compute(f"invoice:{shipment_id}", priced)


def _a_budget_for_the_split(policy: Policy) -> RunBudget:
    """A fresh allowance for the triage pass."""
    return RunBudget(policy)


def _a_ledger_for_the_split() -> RunLedger:
    """A fresh record for the triage pass, kept apart from each product's own."""
    return RunLedger()
