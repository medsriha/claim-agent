"""Investigating a whole claim: split it, look into each product, then check the total.

A merchant opens one claim, and it can cover several damaged products. This file is
what turns that into work: it asks the triage pass which products are being claimed
for, then investigates each of them, then does the one thing that cannot be done a
product at a time.

**Each product is investigated on its own, and they run at the same time.** A claim
with four products is four separate investigations, each with its own step
allowance, so a complicated product cannot starve a simple one and a weak product
cannot drag down a well-evidenced one (FR-1b.3, FR-1.3). They run concurrently
because they do not need anything from each other — which is the same fact that
makes them independent in the first place.

**The one thing that has to look at the claim as a whole is the cap.** Three
products at fifty dollars each are individually under a hundred and together are
not, so a cap that only ever saw one product at a time could be got round by
splitting a claim into more products — exactly what FR-1.20 warns about. So after
every product has been judged on its own evidence, the payments being recommended
are added up and checked once. Nothing is trimmed to fit: if they come to more than
the cap, every product recommended for payment goes to a person instead, and the
claim says why. Whether the cap is meant per product or per claim is an open
question in the requirements, so which of the two happens is a setting.

Nothing here reads a clock, and nothing here decides anything about a product that
the product's own investigation did not already decide — apart from that cap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
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
    """Everything an investigation established about one claim, product by product.

    `triage` is how the claim was split and what was settled about the evidence
    covering the whole shipment. `lines` is one finished investigation per damaged
    product, each with its own recommendation, amount, reasoning and drafted email.

    `lines` is empty when the split could not be established: nothing may be
    investigated until somebody has said which products are being claimed for, so
    the claim goes to a representative instead (FR-1a.4). `triage.ambiguity` says
    what was unclear.

    `claim_concerns` are things about the claim as a whole rather than any one
    product — today that means the cap being reached across several products.
    `recommended_total_usd` is what the products recommended for payment come to
    between them, worked out by arithmetic like every other figure here (FR-1.21).
    """

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
    """Investigate every damaged product on one claim (FR-1a.*, FR-1b.*).

    Only ever called for a claim the deterministic screen let through. A claim it
    stopped costs three cheap reads and no AI at all, and this is never reached
    (NFR-8).

    Args:
        record: The case, its shipment and its order, already read by the screen.
        context: The facts the screen worked out — what the order was worth, whether
            it counts as high value, and what a representative has corrected for
            this merchant before (FR-0.5).
        evidence: The reader for the case's images and for a priced invoice.
        fetcher: How an image is downloaded so a model can look at it.
        chat: The model the investigation asks, with tools bound to it per run.
        structured: The same model, wrapped so an answer either fits its form or
            fails (NFR-2).
        events: Where the whole claim narrates itself while it works. One stream
            for the claim, shared by every product, so a screen watching several at
            once can put every message in one order.
        policy: The thresholds every judgement is made against (FR-0.7).
        cache: The claim's memo of expensive answers, so an image is looked at once
            for the whole claim rather than once per product (NFR-8). One is made
            if none is given; pass one in only to inspect it afterwards.
        precedent_store: The closed claims this service has already handled (FR-S.1).
            Each product is looked up in it before being investigated, so a claim is
            judged the way comparable claims actually were rather than from its own
            evidence alone — which is the whole of what makes two alike claims get
            alike answers (FR-S.5, FR-S.6). `None` skips the lookup entirely, and the
            runs are then told that nobody looked rather than that there was nothing
            to find (FR-S.13).

    Returns:
        The split, and one finished investigation per damaged product. Never raises
        for anything that can happen to a claim: a triage that could not settle the
        split, a product whose run gave up, and a model that could not be reached
        all come back as something a representative can act on (NFR-4).
    """
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
        # claimed for. Guessing a split is silent and expensive; asking is neither
        # (FR-1a.4).
        logger.info("claim_split_unsettled", case_id=triage.case_id, ambiguity=triage.ambiguity)
        return ClaimInvestigation(case_id=triage.case_id, triage=triage)

    invoice = await _invoice_if_one_can_be_had(record=record, evidence=evidence, cache=shared_cache)

    # Looked up before the products fan out, and one product at a time. The store is a
    # file on disk and reading it blocks, so doing it here keeps that off the runs that
    # are about to happen at once. It also means every run starts with its precedent
    # already in hand, which is what FR-S.6 asks for: precedent arrives with the claim
    # and is never something a model decides to go looking for.
    precedent = _precedent_for_each(
        store=precedent_store, case=record.case, lines=triage.claim_lines, policy=policy
    )

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
    """Look up the closed claims most like each product, before any of them is investigated.

    One lookup per product, because from here on each product is its own claim
    (FR-1b.1, FR-S.5). Done in one pass rather than inside the runs: the store is a file
    on disk and reading it blocks, and a blocking read inside runs that are meant to
    happen at once would hold the others up.

    Args:
        store: Where closed claims are kept. `None` when no store was given, which
            returns nothing at all — the runs are then told nobody looked, rather than
            being told there was nothing to find (FR-S.13).
        case: The claim in hand, read for the merchant's account of what happened.
        lines: The products about to be investigated.
        policy: How many records each product sees, and how alike is alike enough.

    Returns:
        A set per claim line, by claim line id. A store that could not be read gives a
        set that says so rather than raising: precedent failing must never fail a claim
        (FR-S.13, NFR-4).
    """
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


class ClaimCapVerdict(BaseModel):
    """What the cap makes of a whole claim, once each product has been judged alone.

    `lines` are the products as they now stand: unchanged when the total is within the
    cap, and with every recommended payment turned into an escalation when it is not.
    `total_usd` is what those payments came to between them, and `complaint` is the one
    plain sentence explaining a breach — `None` when there was none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[LineInvestigation, ...]
    total_usd: Decimal
    applied: bool
    complaint: str | None = None


def apply_claim_cap(lines: Sequence[LineInvestigation], *, policy: Policy) -> ClaimCapVerdict:
    """Add up what is being recommended and apply the cap across the whole claim (FR-1.20).

    Pure, and deliberately separate from the narration around it: this is the one rule
    in the system that no single product can apply for itself, which makes it the one
    most worth being able to test on its own.
    """
    total = sum(
        (
            line.amount.amount_usd
            for line in lines
            if line.outcome.recommendation is Recommendation.APPROVE
        ),
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
    """Add up what is being recommended and apply the cap across the whole claim (FR-1.20).

    This is the one judgement in the system that a single product cannot make for
    itself, and the only place a product's outcome depends on what else was claimed
    beside it. Everything else about a product is decided from its own evidence, which
    is what makes a product reach the same answer whether it was claimed alone or with
    five others (FR-1b.4).

    Where the total is over the cap, nothing is trimmed and nothing is chosen between:
    every product that was recommended for payment goes to a representative instead,
    carrying its findings and a sentence saying why. Trimming would put a figure in
    front of a merchant that no rule produced.

    Whether the cap is meant to limit each product or the whole claim is open question
    2 in the requirements, so it is a setting rather than a decision made here.
    """
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
    """Turn one product's recommended payment into an escalation, keeping everything else.

    Only a product recommended for payment changes. A product already going back to
    the merchant or already going to a person is untouched: the cap is a reason not to
    pay, never a reason to pay, and never a reason to stop asking for a photograph.

    What the investigation originally recommended is kept beside the new answer, as it
    is for every other rule that withholds a payment, so a representative can see that
    the product itself was sound and the claim's total was not.
    """
    if line.outcome.recommendation is not Recommendation.APPROVE:
        return line

    return line.model_copy(
        update={
            "outcome": OutcomeDecision(
                recommendation=Recommendation.ESCALATE,
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


async def _invoice_if_one_can_be_had(
    *, record: CaseRecord, evidence: EvidenceClient, cache: ObservationCache
) -> Invoice | None:
    """Fetch the priced invoice once for the whole claim, or come back with nothing.

    Every product is priced from the same invoice, so it is fetched once here rather
    than once per product (NFR-8). `None` means it could not be had — ShipBob would not
    price this shipment, or the case names no shipment or no merchant — and the products
    that needed a price then escalate with that as the stated reason rather than being
    priced from somewhere else (FR-1.18).
    """
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
    """A fresh allowance for the triage pass.

    Its own, not shared with any product's run: a claim with four products has five
    allowances in total, not one divided five ways (FR-1.3).
    """
    return RunBudget(policy)


def _a_ledger_for_the_split() -> RunLedger:
    """A fresh record for the triage pass, kept apart from each product's own."""
    return RunLedger()
