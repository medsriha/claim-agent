from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import ClaimFindings, investigate_claim_lines
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.precedent_context import precedent_for_claim
from claim_agent.agent.threads import PassThreads
from claim_agent.agent.triage import ClaimTriage, triage_claim
from claim_agent.domain.models import Invoice
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet, PrecedentStore

logger = get_logger(__name__)


class ClaimInvestigation(BaseModel):
    """Everything an investigation established about one claim (FR-1b.1).

    `findings` is `None` only when nothing could be investigated, which happens when the
    claim could not be split into products at all — guessing a split is what FR-1a.4
    forbids, so there is nothing to have found.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    triage: ClaimTriage
    findings: ClaimFindings | None = None


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
    threads: PassThreads | None = None,
) -> ClaimInvestigation:
    """Split a claim into products, then investigate all of them in one run (FR-1a.*, FR-1b.*).

    `threads` is where the investigation's conversation is kept. A fresh thread is started
    for every investigation, so investigating a claim again never appends to the last
    time's evidence; a rework of the report this produces continues the thread (FR-R.2).
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
        # claimed for. Guessing a split is silent and expensive; asking the party who
        # can settle it is neither (FR-1a.4).
        logger.info("claim_split_unsettled", case_id=triage.case_id, ambiguity=triage.ambiguity)
        return ClaimInvestigation(case_id=triage.case_id, triage=triage)

    invoice = await invoice_for_claim(record=record, evidence=evidence, cache=shared_cache)

    # Looked up before the run starts: the store is a file on disk and reading it blocks. It
    # also means the run begins with its precedent already in hand, which is what FR-S.6 asks
    # for — precedent arrives with the claim, never fetched on a whim.
    precedent = _precedent_for_the_claim(
        store=precedent_store, record=record, triage=triage, policy=policy
    )
    await _say_what_precedent_was_found(precedent, events=events)

    findings = await investigate_claim_lines(
        lines=triage.claim_lines,
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
        precedent=precedent,
        thread=threads.start(record.case.case_id) if threads is not None else None,
    )

    return ClaimInvestigation(case_id=triage.case_id, triage=triage, findings=findings)


def _precedent_for_the_claim(
    *,
    store: PrecedentStore | None,
    record: CaseRecord,
    triage: ClaimTriage,
    policy: Policy,
) -> PrecedentSet | None:
    """Look up the closed claims most like this one, before it is investigated (FR-S.5)."""
    if store is None:
        return None
    return precedent_for_claim(
        store=store,
        case=record.case,
        lines=triage.claim_lines,
        policy=policy,
        shared_evidence=(),
    )


async def _say_what_precedent_was_found(
    precedent: PrecedentSet | None, *, events: EventStream
) -> None:
    """Tell whoever is watching what comparable past claims were found."""
    if precedent is None:
        summary = "No past claims were looked up for this claim."
        outcome = "not_looked_up"
        count = 0
    elif not precedent.was_read:
        summary = (
            "Past claims could not be read, so nothing is known about how claims like "
            "this one were handled."
        )
        outcome = "unreadable"
        count = 0
    elif not precedent.retrieved:
        summary = "No past claim close enough to this one was found."
        outcome = "none_alike"
        count = 0
    else:
        count = len(precedent.retrieved)
        summary = (
            f"Found {count} past claim(s) like this one, out of {precedent.considered} looked at."
        )
        outcome = "found"

    await events.emit(EventKind.PRECEDENT_GATHERED, summary, outcome=outcome, found=str(count))


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
    """A fresh record for the triage pass, kept apart from the investigation's own."""
    return RunLedger()
