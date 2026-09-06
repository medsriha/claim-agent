"""The triage pass: which products a claim is for, and what its shared evidence is (FR-1a)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import BudgetSnapshot, RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import LedgerEntry, RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.loop import run_agent_pass
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import build_triage_messages
from claim_agent.agent.schemas import ClaimSplit
from claim_agent.agent.tools import (
    LIST_ATTACHMENTS,
    TRIAGE_TOOL_NAMES,
    AttachmentClassification,
    ImageLog,
    investigation_tools,
)
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome, build_claim_lines
from claim_agent.domain.evidence import (
    SHARED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import Attachment, Order
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient

logger = get_logger(__name__)

TRIAGE_CLOSING_REQUEST: Final = (
    "Say which products this claim is for. Name each one as the order writes it, and say "
    "how many of it were damaged. If you cannot tell which product is meant, say that you "
    "cannot, say what is unclear, and say what would settle it — do not choose. If the "
    "merchant can settle it, name every detail they must provide and draft the email asking "
    "for them; otherwise leave the merchant-request and email fields empty."
)


class ClaimTriage(BaseModel):
    """What the claim turned out to be about: the whole answer of the triage pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    attachments: tuple[Attachment, ...] = ()
    claim_lines: tuple[ClaimLine, ...] = ()
    shared_evidence: tuple[EvidenceFinding, ...] = ()
    ambiguity: str | None = None
    attachment_classifications: tuple[AttachmentClassification, ...] = ()
    split: ClaimSplit | None = None
    ledger: tuple[LedgerEntry, ...] = ()
    budget: BudgetSnapshot

    @property
    def is_ambiguous(self) -> bool:
        """Whether the split was left unsettled and no product may be investigated."""
        return self.ambiguity is not None


async def triage_claim(
    *,
    record: CaseRecord,
    context: ClaimContext,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    cache: ObservationCache,
    budget: RunBudget,
    ledger: RunLedger,
    events: EventStream,
    policy: Policy,
) -> ClaimTriage:
    """Work out which products a claim is for, and settle its shared evidence (FR-1a.1)."""
    case = record.case

    try:
        attachments = await evidence.list_attachments(case.case_id)
    except ClaimAgentError as failure:
        return await _could_not_look_at_the_claim(
            case_id=case.case_id, failure=failure, budget=budget, ledger=ledger, events=events
        )

    await events.emit(
        EventKind.ATTACHMENTS_LISTED,
        "This claim has no images at all."
        if not attachments
        else f"This claim has {len(attachments)} image(s).",
        count=str(len(attachments)),
    )

    # The inspect tool notes what each image turned out to be here, as it happens.
    images = ImageLog(events)
    tools = investigation_tools(
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
        names=TRIAGE_TOOL_NAMES,
        images=images,
    )

    outcome = await run_agent_pass(
        opening_messages=build_triage_messages(
            case=case, order=record.order, attachments=attachments, context=context
        ),
        tools=tools,
        concludes_with=ClaimSplit,
        closing_request=TRIAGE_CLOSING_REQUEST,
        chat=chat,
        structured=structured,
        budget=budget,
        ledger=ledger,
        events=events,
    )

    # Settled from what the pass observed, even when it gave up before concluding (FR-1.16).
    classifications = images.classifications()
    shared = _settle_shared_evidence(classifications)
    await _say_what_the_evidence_showed(events, shared)

    split = outcome.answer
    lines = () if split is None else _claim_lines_from(case.case_id, split, record.order)
    ambiguity = outcome.reason if split is None else _what_is_unclear(split, lines)

    logger.info(
        "claim_triaged",
        case_id=case.case_id,
        claim_lines=len(lines),
        images_classified=len(classifications),
        ambiguous=ambiguity is not None,
    )
    await _say_how_the_claim_was_split(events, lines, ambiguity)

    return ClaimTriage(
        case_id=case.case_id,
        attachments=attachments,
        claim_lines=lines,
        shared_evidence=shared,
        ambiguity=ambiguity,
        attachment_classifications=classifications,
        split=split,
        ledger=outcome.ledger,
        budget=outcome.budget,
    )


def _settle_shared_evidence(
    classifications: Sequence[AttachmentClassification],
) -> tuple[EvidenceFinding, ...]:
    """Settle the three pieces of evidence that describe the parcel, once (FR-1a.3)."""
    # An image we could not read might have been any of the three, so it bears on all.
    something_unreadable = any(
        classified.state is EvidenceState.UNREADABLE for classified in classifications
    )
    return tuple(
        _finding_for(kind, classifications, something_unreadable=something_unreadable)
        for kind in SHARED_EVIDENCE
    )


def _finding_for(
    kind: EvidenceKind,
    classifications: Sequence[AttachmentClassification],
    *,
    something_unreadable: bool,
) -> EvidenceFinding:
    """Decide what the claim holds for one piece of shared evidence."""
    of_this_kind = sorted(
        (classified for classified in classifications if classified.kind is kind),
        key=lambda classified: classified.attachment_id,
    )
    named = _readable(kind)

    usable = next((found for found in of_this_kind if found.state is EvidenceState.PRESENT), None)
    if usable is not None:
        return EvidenceFinding(
            kind=kind,
            state=EvidenceState.PRESENT,
            observed=usable.observed,
            attachment_id=usable.attachment_id,
        )

    too_poor = next(
        (found for found in of_this_kind if found.state is EvidenceState.UNUSABLE), None
    )
    if too_poor is not None:
        return EvidenceFinding(
            kind=kind,
            state=EvidenceState.UNUSABLE,
            observed=too_poor.observed,
            attachment_id=too_poor.attachment_id,
            problem=too_poor.problem,
        )

    if something_unreadable:
        return EvidenceFinding(
            kind=kind,
            state=EvidenceState.UNREADABLE,
            observed=(
                f"No image on this claim was found to be the {named}, and at least one "
                "image could not be read at all, so it cannot be said whether one was sent."
            ),
            problem=(
                "An image this system could not read may have been this evidence. The "
                "merchant cannot do anything about that and must not be asked to."
            ),
        )

    return EvidenceFinding(
        kind=kind,
        state=EvidenceState.MISSING,
        observed=f"No image on this claim was found to be the {named}.",
    )


def _claim_lines_from(
    case_id: str, split: ClaimSplit, order: Order | None
) -> tuple[ClaimLine, ...]:
    """Turn the products the pass named into claim lines matched to the order (FR-1a.2)."""
    proposals = split.claimed_products
    return build_claim_lines(
        case_id,
        [
            ClaimedProduct(name=proposal.name, quantity=proposal.quantity, sku=proposal.sku)
            for proposal in proposals
        ],
        order,
        [proposal.damage_attachment_ids for proposal in proposals],
    )


def _what_is_unclear(split: ClaimSplit, lines: Sequence[ClaimLine]) -> str | None:
    """Say what stops this split being acted on, or `None` when nothing does (FR-1a.4)."""
    if split.is_ambiguous:
        return split.ambiguity or (
            "The investigation could not establish which products this claim is for."
        )

    if not split.claimed_products:
        return (
            "The investigation named no damaged products, so there is nothing to "
            "investigate. Somebody has to establish what this claim is for."
        )

    unresolved = [line for line in lines if line.match is MatchOutcome.AMBIGUOUS]
    if not unresolved:
        return None

    described = "; ".join(
        f"{line.claimed.name} could be any of: "
        + ", ".join(candidate.name for candidate in line.candidate_order_lines)
        for line in unresolved
    )
    return (
        "More than one product on the order could be what was claimed, and the "
        f"candidates can carry different prices, so choosing would invent the payout. "
        f"{described}."
    )


async def _could_not_look_at_the_claim(
    *,
    case_id: str,
    failure: ClaimAgentError,
    budget: RunBudget,
    ledger: RunLedger,
    events: EventStream,
) -> ClaimTriage:
    """Give up before the pass starts, because the claim's images could not be listed."""
    logger.warning("claim_triage_no_attachment_listing", case_id=case_id, failure=failure.code)
    ledger.record(
        kind=StepKind.TOOL_CALL,
        name=LIST_ATTACHMENTS,
        asked=f"List the images on case {case_id}.",
        observed=failure.message,
        succeeded=False,
        reference=case_id,
    )
    unreadable = tuple(
        EvidenceFinding(
            kind=kind,
            state=EvidenceState.UNREADABLE,
            observed="The images on this claim could not be listed at all.",
            problem=(
                "This system could not read what the merchant sent. They cannot do "
                "anything about that and must not be asked to."
            ),
        )
        for kind in SHARED_EVIDENCE
    )
    ambiguity = (
        "The images on this claim could not be listed, so which products it is for "
        f"could not be established. {failure.message}"
    )
    await _say_what_the_evidence_showed(events, unreadable)
    await _say_how_the_claim_was_split(events, (), ambiguity)

    return ClaimTriage(
        case_id=case_id,
        ambiguity=ambiguity,
        shared_evidence=unreadable,
        ledger=ledger.entries(),
        budget=budget.snapshot(),
    )


async def _say_what_the_evidence_showed(
    events: EventStream, findings: Sequence[EvidenceFinding]
) -> None:
    """Announce each piece of shared evidence, one message apiece, in the fixed order."""
    for finding in findings:
        detail = {"evidence_kind": finding.kind.value, "state": finding.state.value}
        if finding.attachment_id is not None:
            detail["attachment_id"] = finding.attachment_id
        await events.emit(EventKind.EVIDENCE_SETTLED, _evidence_sentence(finding), **detail)


async def _say_how_the_claim_was_split(
    events: EventStream, lines: Sequence[ClaimLine], ambiguity: str | None
) -> None:
    """Announce what the claim turned out to be about, settled or not."""
    if ambiguity is not None:
        await events.emit(
            EventKind.CLAIM_SPLIT,
            f"This claim could not be split into products. {ambiguity}",
            products=str(len(lines)),
            settled="no",
        )
        return

    named = ", ".join(line.product_name for line in lines)
    await events.emit(
        EventKind.CLAIM_SPLIT,
        f"This claim is for {len(lines)} product(s): {named}.",
        products=str(len(lines)),
        settled="yes",
    )


def _evidence_sentence(finding: EvidenceFinding) -> str:
    """One plain sentence about one piece of shared evidence, for the screen."""
    named = _readable(finding.kind)
    if finding.state is EvidenceState.PRESENT:
        return f"The {named} is there, in image {finding.attachment_id}."
    if finding.state is EvidenceState.UNUSABLE:
        return f"The {named} arrived but cannot be relied on — {finding.problem}"
    if finding.state is EvidenceState.UNREADABLE:
        return f"The {named} could not be settled, because an image could not be read."
    return f"The {named} is missing."


def _readable(kind: EvidenceKind) -> str:
    """Write one of the four kinds of evidence the way a person says it aloud."""
    return kind.value.replace("_", " ")
