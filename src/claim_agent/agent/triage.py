"""Working out which products a claim is for, and settling the shared evidence once.

A merchant opens **one** support case for **one** parcel, and that parcel may have
held several damaged products. Almost everything after this point works on one
product at a time, because ShipBob pays for one product per call and because a
representative may well want to pay for one item while asking for a better
photograph of another. So the claim has to be split first, and this file is that
split (FR-1a.1).

The split cannot be worked out by a rule. The merchant's description does not name
products — it says things like "1 order affected" — so which products are meant can
only be established by reading their account and looking at the photographs. That is
one pass of the investigation over the whole claim.

**Nothing here decides which images to look at.** The pass is given the four tools
and the question, and it chooses: a claim whose description already names a product
may cost one photograph, a claim with none costs none at all (FR-1.1). There is
deliberately no loop in this file that classifies every attachment in turn before the
pass begins — that would be a fixed sequence wearing an agent's clothes, and it would
pay to look at photographs nobody needed (NFR-8).

**The shared evidence is settled here, once, for the whole claim (FR-1a.3).** Three
of the four things a reimbursement needs — the invoice, the customer's confirmation
that the parcel arrived damaged, and a photograph of the outer box — describe the
parcel rather than any one product in it. They are worked out from whatever the pass
looked at and handed unchanged to every product's investigation. That is partly to
avoid re-reading the same invoice once per product, and mostly so that two products
in one claim can never disagree about whether the box was photographed. The fourth
thing, a photograph of the damaged product itself, belongs to one product and is not
settled here.

**A claim this pass cannot split is sent to whoever can resolve it, not guessed at (FR-1a.4).**
Orders hold similar products at different prices; CASE-1002 holds two different 24oz
bottles, one costing twice the other. Choosing between them would invent the payout,
so an unclear split comes back saying exactly what is unclear. When the merchant can
answer a concrete question, the result names those details for an email; internal or
non-actionable ambiguity stays with the representative (FR-1.13).

**Nothing here raises for an ordinary failure.** A pass that ran out of steps, a
model that could not be reached, images that could not be listed: each one comes back
as a triage that says it is unclear, carrying everything the run did establish, so
the claim reaches a person rather than an error page (FR-1.16, NFR-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from langchain_core.callbacks import AsyncCallbackHandler
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
from claim_agent.agent.tools import LIST_ATTACHMENTS, ImageInspection, investigation_tools
from claim_agent.domain.assessment import Confidence
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
"""What the pass is asked once it has stopped looking at things.

The words a model reads belong with the other prompts rather than in the code that
happens to ask the question. This one is here because there is nowhere for it in
`claim_agent.agent.prompts` yet; it should move there alongside the triage question
it closes.
"""


class AttachmentClassification(BaseModel):
    """What one image the investigation looked at turned out to be (FR-1.4).

    An image on a claim arrives with a name that proves nothing — `329233.png`,
    `Inv.png`, two screenshots thirteen seconds apart — so what an image holds can
    only be settled by looking at it. This is the answer for one image, kept so that
    a representative can see what the system saw rather than only what it concluded.

    Only images the investigation actually chose to look at appear. An image nobody
    looked at is absent from the list entirely, which is not the same as an image
    that turned out to be nothing useful.

    Fields:
        attachment_id: ShipBob's id for the image, so a finding can always be traced
            back to the exact picture it came from (FR-2.2).
        kind: Which of the four kinds of evidence the image is, or `None` when it is
            none of them — a photograph of a shipping label, say — or when nothing
            could be read from it at all.
        state: What can be done with the image itself, which is deliberately a
            statement about the picture rather than about a requirement. `PRESENT`
            means it was read and can be relied on; `UNUSABLE` means it arrived too
            dark, blurry or cropped to conclude anything from, which the merchant can
            fix (FR-1.5); `UNREADABLE` means **we** could not fetch it or get an
            answer about it, which the merchant cannot fix and must not be asked to
            (NFR-4). `MISSING` never appears here: an image we are holding is not a
            missing one.
        observed: One plain sentence saying what was seen, or why nothing could be.
        problem: Why the image cannot be relied on, and `None` when it can. For an
            `UNUSABLE` image these are words the merchant could act on; for an
            `UNREADABLE` one they describe a fault on our side.
        confidence: How sure the reading was, from 0 to 1. `None` when the image was
            never successfully looked at, so there is nothing to be sure about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str
    kind: EvidenceKind | None = None
    state: EvidenceState
    observed: str
    problem: str | None = None
    confidence: Confidence | None = None


class ClaimTriage(BaseModel):
    """What the claim turned out to be about — the whole answer of Layer 1a.

    This is what the per-product investigations are built from. Read `ambiguity`
    first: while there is something in it, the split was not established and no
    per-product investigation should be started from these lines. The claim asks the
    merchant when they can provide specific missing details; otherwise it goes to a
    representative (FR-1a.4, FR-1.13).

    Frozen, because it is the account of a pass that has already run.

    Fields:
        case_id: The claim this is the triage of.
        attachments: Every image on the claim, in the order ShipBob listed them,
            whether or not the pass looked at it. Carried so that whoever
            investigates a product does not have to ask ShipBob for the same listing
            again.
        claim_lines: One line per product the investigation says was damaged, each
            matched against the order (FR-1a.2). A claim covering a single product is
            one line through exactly the same machinery, with no special case for it
            (FR-1a.5). Empty when nothing was established — which is normal for a
            pass that gave up.

            **Lines are still here when the split is unclear.** They are the
            candidates the pass was choosing between, not a settled answer, and
            reporting them is what lets a representative see the choice rather than
            just being told there was one.
        shared_evidence: The invoice, the customer's confirmation and the outer
            packaging photograph, settled once for the whole claim and in the fixed
            reporting order (FR-1a.3). Every product's investigation is handed this
            same answer. The damaged-product photograph is not here: it belongs to
            one product and is settled by that product's own run.
        ambiguity: What is unclear about the split, in actionable words, or `None`
            when nothing is. It is also where a pass that failed
            outright says why, because from the outside "we could not tell" and "we
            could not finish" both mean the claim needs a person (NFR-4).
        attachment_classifications: What each image the pass looked at turned out to
            be. An image looked at more than once appears once.
        split: What the pass concluded, in its own words — its reasoning and how sure
            it was. `None` when the pass gave up before concluding, and then
            `ambiguity` holds the reason.
        ledger: Every step the pass took, in order, so a representative can audit how
            the split was reached (NFR-3). Present even when the pass gave up: what
            was established is carried forward rather than lost (FR-1.16).
        budget: What the pass spent and which of its limits it reached, so an
            representative clarification request can be explained without anyone reading logs.
    """

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
        """Whether the split was left unsettled and no product may be investigated.

        Worked out from `ambiguity` rather than stored beside it, so the two can
        never contradict each other. A stored flag would eventually be set wrong in
        one branch, and a caller trusting it would investigate products the system had
        refused to choose between. The split separately says whether the merchant can
        provide the missing details or a representative must resolve it (FR-1a.4).
        """
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
    """Work out which products a claim is for, and settle its shared evidence (FR-1a.1).

    One pass of the investigation over the whole claim. It is handed the four tools
    and the question, and it decides for itself which photographs are worth looking
    at (FR-1.1); nothing here looks at one on its own account.

    Never raises for anything that can happen to a claim. A pass that gave up, a
    model that could not be reached, images that could not be listed: each comes back
    as a triage whose `ambiguity` says so, carrying whatever the run established, so
    the claim reaches a representative (FR-1.16, NFR-4).

    Args:
        record: What the pre-flight screen read — the claim, its parcel and its
            order (FR-0.1). The order is the only list of products a claim line may
            name, and is `None` when it could not be read, which makes every line a
            product that is on no order rather than a match against nothing.
        context: The facts the pre-flight screen worked out, so the pass does not
            spend steps rediscovering them (FR-0.5).
        evidence: Reads the claim's images and asks ShipBob to price the shipment.
        fetcher: Turns an image's address into the picture itself.
        chat: The model the pass asks what to do next, with the tools bound to it.
        structured: The same model, wrapped so an answer either fits the form or
            fails (NFR-2). Used for the pass's conclusion and for reading images.
        cache: This claim's memo of expensive answers, so one photograph is never
            analysed twice (NFR-8). Build one per claim and hand the same one to the
            per-product runs that follow.
        budget: This pass's own allowance. Build a fresh one: the per-product runs
            that follow get their own, and a shared budget is refused outright
            (FR-1.3).
        ledger: Where each step is written down as it happens (NFR-3).
        events: Where the pass narrates itself while it works. Shared by the whole
            claim.
        policy: The claim thresholds, read for the run's limits and the
            reimbursement cap (FR-0.7, NFR-7).

    Returns:
        The claim's products, its shared evidence, and the record of how both were
        reached. Read `ambiguity` before acting on the lines.
    """
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

    watcher = _ImageWatcher(events)
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
    )
    for tool in tools:
        # Attached here rather than asked for from the tools, because what an image
        # turned out to be is the pass's finding and this file is what has to settle
        # the shared evidence from it. Listening as the calls happen is also what
        # lets each image be announced while the pass is still working.
        tool.callbacks = [watcher]

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

    # Settled from what the pass observed, even when it gave up before concluding.
    # What it managed to establish is worth carrying forward either way (FR-1.16).
    classifications = watcher.classifications()
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


class _ImageWatcher(AsyncCallbackHandler):
    """Notices what each image turned out to be, at the moment the pass looks at it.

    The pass chooses which photographs to look at, so the only way to know what it
    saw is to watch it. This listens to every tool call the pass makes and keeps the
    answers the image tool gave, which is what the shared evidence is then settled
    from.

    Watching is also the honest way to narrate it. An image is announced as it is
    classified rather than in a batch afterwards, so somebody following the claim
    sees the investigation working rather than a finished list appearing at the end.

    Nothing else is kept: a call that priced the shipment or checked an amount is
    read and ignored, and a call that established nothing about an image — a bad id,
    an allowance already used up — is ignored too, because the tool has already said
    so in its own words.
    """

    def __init__(self, events: EventStream) -> None:
        """Start watching, announcing each image on the given stream as it is read."""
        self._events = events
        self._seen: list[AttachmentClassification] = []

    async def on_tool_end(self, output: object, **_unused: object) -> None:
        """Take the answer from one finished tool call, and say so if it was an image.

        Args:
            output: What the tool answered with. Only a look at an image carries
                anything of interest here; everything else is left alone.
            **_unused: Which run the call belonged to and how it was tagged, none of
                which this needs.
        """
        classified = _classification_of(output)
        if classified is None:
            return

        self._seen.append(classified)
        await self._events.emit(
            EventKind.IMAGE_CLASSIFIED,
            _what_the_image_was(classified),
            attachment_id=classified.attachment_id,
            evidence_kind="none" if classified.kind is None else classified.kind.value,
            state=classified.state.value,
        )

    def classifications(self) -> tuple[AttachmentClassification, ...]:
        """What each image looked at turned out to be, one entry per image.

        An image the pass asked about twice — once in general and once about
        something particular — appears once, and the answer that established what the
        image *is* wins over one that only answered a question about it. Otherwise a
        photograph identified as the invoice on the first look could stop counting as
        one because a later, narrower question did not mention it.

        Ordered by when each image was first looked at. Empty when the pass looked at
        no images, which is an ordinary answer and the only possible one for a claim
        with no images at all (FR-1.6).
        """
        best: dict[str, AttachmentClassification] = {}
        for classified in self._seen:
            settled = best.get(classified.attachment_id)
            if settled is None or (settled.kind is None and classified.kind is not None):
                best[classified.attachment_id] = classified
        return tuple(best.values())


def _classification_of(output: object) -> AttachmentClassification | None:
    """Read one finished tool call, and say what it established about an image.

    `None` means this call has nothing to say here: it was not a look at an image, or
    it was a look that never got as far as an answer — an id that is on no image, an
    image allowance already spent. Those are the model's problem to work around and
    the tool has already told it so, and treating them as findings would put images
    in the record that were never actually read.
    """
    artifact = getattr(output, "artifact", None)
    if not isinstance(artifact, ImageInspection):
        return None

    if artifact.state is EvidenceState.UNREADABLE:
        # Ours, not the merchant's. Nothing was seen, so there is no kind and no
        # confidence — only the fact that we could not look (NFR-4).
        return AttachmentClassification(
            attachment_id=artifact.attachment_id,
            state=EvidenceState.UNREADABLE,
            observed="This image could not be read by this system.",
            problem=artifact.summary,
        )

    observation = artifact.observation
    if observation is None:
        return None

    return AttachmentClassification(
        attachment_id=artifact.attachment_id,
        kind=observation.kind,
        # An image the model could read is present as an image, whatever it turned
        # out to hold. Whether the claim has the evidence it needs is a separate
        # question, settled below.
        state=EvidenceState.UNUSABLE if not observation.is_legible else EvidenceState.PRESENT,
        observed=observation.shows,
        problem=observation.problem,
        confidence=observation.confidence,
    )


def _settle_shared_evidence(
    classifications: Sequence[AttachmentClassification],
) -> tuple[EvidenceFinding, ...]:
    """Settle the three pieces of evidence that describe the parcel, once (FR-1a.3).

    The invoice, the customer's confirmation and the photograph of the outer box are
    facts about the shipment rather than about any one product in it, so they are
    worked out here and the same answer is handed to every claim line. Two products
    in one claim can then never disagree about whether the box was photographed.

    Always returns all three, in the fixed reporting order, present or not — a
    representative should see what was found rather than infer it from silence
    (FR-2.2).
    """
    # Asked once for the whole set: an image we could not read might have been any of
    # the three, so it bears on all of them.
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
    """Decide what the claim holds for one piece of shared evidence.

    Four answers, in the order they are preferred:

    1. An image the pass read and found to be this — the evidence is **present**.
    2. An image found to be this but too poor to rely on — **unusable**, and the
       merchant can be asked for a better one (FR-1.5, FR-1.7).
    3. Neither, but some image on the claim could not be read by us — **unreadable**.
       We genuinely cannot say whether this was sent, so a person looks rather than
       the merchant being asked for something they may already have sent (NFR-4).
    4. Neither, and every image was read — **missing**.

    Where two images are both this piece of evidence, the one whose id sorts first is
    named. Any of them would do, and choosing by id rather than by the order the pass
    happened to look means two runs of the same claim name the same image (NFR-1).
    """
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
    """Turn the products the pass named into claim lines matched to the order (FR-1a.2).

    A product the order does not hold still becomes a line: a merchant claiming for
    something they never ordered is a finding a representative needs to see, not a
    record to drop quietly. One product makes one line, through the same machinery as
    four (FR-1a.5).

    The photographs the pass tied to each product travel with the line as a starting
    point for that product's own investigation, which may look elsewhere and may
    disagree.
    """
    proposals = split.claimed_products
    # Both lists are read off the same proposals, so they always have the same
    # length, which is the one thing `build_claim_lines` refuses.
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
    """Say what stops this split being acted on, or `None` when nothing does (FR-1a.4).

    Three separate ways a split can fail to settle anything. All stop the system from
    choosing; the split's requested details separately decide whether the merchant or
    a representative is asked to resolve it (FR-1.13):

    * the pass says outright that it could not tell which products are meant;
    * it named no products at all, which is not an answer to "which products";
    * it named a product that more than one line of the order could be, so the two
      candidates may carry different prices and choosing would invent the payout.
    """
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
    """Give up before the pass starts, because the claim's images could not be listed.

    Without the listing there is no honest question to ask. Telling the pass that a
    claim has no images when we simply could not look would invite a split made
    against evidence nobody checked for, so the claim goes to a person instead
    (NFR-4).

    Every piece of shared evidence is recorded as unreadable rather than missing: we
    do not know what the merchant sent, and asking them to send it again is a request
    they cannot act on (FR-1.7).

    The evidence and the split are still announced, exactly as they are on a pass that
    ran. A watcher whose stream simply stopped would have no way of telling a claim
    that failed from one still being worked on.
    """
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
    """Announce each piece of shared evidence, one message apiece, in the fixed order.

    All three are announced whether or not they were found, so somebody watching sees
    what was checked rather than inferring it from silence.
    """
    for finding in findings:
        detail = {"evidence_kind": finding.kind.value, "state": finding.state.value}
        if finding.attachment_id is not None:
            detail["attachment_id"] = finding.attachment_id
        await events.emit(EventKind.EVIDENCE_SETTLED, _evidence_sentence(finding), **detail)


async def _say_how_the_claim_was_split(
    events: EventStream, lines: Sequence[ClaimLine], ambiguity: str | None
) -> None:
    """Announce what the claim turned out to be about, settled or not.

    A split nobody could make is said out loud in the same place as one that worked.
    A watcher whose stream simply stopped would have no idea whether the claim was
    still being worked on (NFR-4).
    """
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
    """One plain sentence about one piece of shared evidence, ready to put on screen."""
    named = _readable(finding.kind)
    if finding.state is EvidenceState.PRESENT:
        return f"The {named} is there, in image {finding.attachment_id}."
    if finding.state is EvidenceState.UNUSABLE:
        return f"The {named} arrived but cannot be relied on — {finding.problem}"
    if finding.state is EvidenceState.UNREADABLE:
        return f"The {named} could not be settled, because an image could not be read."
    return f"The {named} is missing."


def _what_the_image_was(classified: AttachmentClassification) -> str:
    """One plain sentence about one image, ready to put on screen as it is read."""
    if classified.state is EvidenceState.UNREADABLE:
        return f"Image {classified.attachment_id}: could not be read by this system."
    if classified.state is EvidenceState.UNUSABLE:
        return f"Image {classified.attachment_id}: too poor to rely on — {classified.problem}"
    if classified.kind is None:
        return f"Image {classified.attachment_id}: none of the four kinds of evidence."
    return f"Image {classified.attachment_id}: {_readable(classified.kind)}."


def _readable(kind: EvidenceKind) -> str:
    """Write one of the four kinds of evidence the way a person says it aloud."""
    return kind.value.replace("_", " ")
