"""The four things an investigation can do, and the one place they are assembled.

An investigation reads and reasons, and that is all. It can list the images on a
claim, look at one of those images and say what it is, ask ShipBob to price the
shipment, and ask ShipBob's own arithmetic whether the products it believes were
damaged could be priced at all. Four things. This file is the whole list (FR-1.2).

**There is no tool here that emails a merchant or pays one, and that absence is the
guarantee.** Not a rule the model is asked to follow — a rule it cannot break,
because the ability is not in its hands. Sending and paying live in
`claim_agent.execution`, which nothing in this package imports and which runs only
after a representative has approved something. If you are ever tempted to add a
fifth tool that changes anything at ShipBob, that is the requirement you would be
deleting.

**A tool never raises into the investigation (NFR-4).** Every failure this system
knows how to have — ShipBob unreachable, an image that will not download, a model
that will not answer, an allowance used up — comes back as an ordinary result the
model can read and reason about, so the run can carry on and still reach a
recommendation, or run out of budget trying. A mistake in *our own* code is the one
thing left to travel, because a defect should look like a defect rather than like
ShipBob being down.

**Two ways of not having a usable image, and they must never be confused.** An image
the merchant sent that is too dark or too cropped to conclude anything from is
*unusable*: they can send another, and the result says so, so they can be asked for
something specific (FR-1.5, FR-1.7). An image *we* could not fetch or could not get
an answer about is *unreadable*: the merchant can do nothing about it, must not be
asked to, and the claim needs a person instead (NFR-4).

**Nothing a tool hands the model carries a recommended amount (FR-1.21).** The
arithmetic tool answers whether an amount could be worked out and never what it is —
see `AmountCheck` for why that line is drawn exactly there. Invoice prices are a
different matter and are shown, for the same stated reason the prompts already show
the order's prices: two similar products at different prices is precisely what the
model must notice and refuse to guess between.

**Every call is written down twice, on purpose.** Once in the run's ledger, which
travels inside the finished report and is how a representative audits a decision
(NFR-3, NFR-5), and once on the event stream, which is how somebody watching sees
the investigation choosing what to look at next while it is still working (FR-1.1).
Failures are written down exactly like successes; a record that only kept the
successes would make a run look tidier than it was.

**A note on where the tool descriptions live.** The sentences below that describe
each tool are words the model reads, and by the rule at the top of `prompts.py` they
belong in that file with every other word we say to it. They are here because a tool
and its description are declared together, and splitting them would let a tool's
arguments and its description drift apart. Worth moving if that file ever grows a
home for them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from typing import Final, TypeVar

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import FetchedImage, ImageFetcher
from claim_agent.agent.ledger import RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import build_image_classification_messages, quote_untrusted
from claim_agent.agent.schemas import AMOUNT_PLACEHOLDER, DamagedItem, ImageObservation
from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.evidence import EvidenceState
from claim_agent.domain.models import Attachment, Invoice, OrderLineItem
from claim_agent.domain.reimbursement import review_recommended_amount
from claim_agent.errors import ClaimAgentError
from claim_agent.policy import Policy
from claim_agent.shipbob.evidence_client import EvidenceClient

# --- What the four tools are called ----------------------------------------

LIST_ATTACHMENTS: Final = "list_attachments"
INSPECT_IMAGE: Final = "inspect_image"
GENERATE_INVOICE: Final = "generate_invoice"
COMPUTE_REIMBURSEMENT: Final = "compute_reimbursement"

TOOL_NAMES: Final = (LIST_ATTACHMENTS, INSPECT_IMAGE, GENERATE_INVOICE, COMPUTE_REIMBURSEMENT)
"""Every tool an investigation has, in one tuple, so the surface can be checked at a glance.

The list is exactly what FR-1.2 permits. A test compares the registry against it, so
adding a tool without deciding that the requirement allows it fails the build.
"""


# --- What the model is told each tool does ---------------------------------
# These four sentences are read by the model, so they say what a tool answers and
# what it costs, and nothing about how it works.

_LIST_ATTACHMENTS_DESCRIPTION: Final = (
    "List the images on this claim. You get their ids and nothing else. A claim with no "
    "images at all is an ordinary answer and not a failure."
)

_INSPECT_IMAGE_DESCRIPTION: Final = (
    "Look at one image on this claim and say what it is and whether it can be relied on. "
    "This is the most expensive thing you can do, and there is a limit on how many images "
    "one run may look at. Asking about the same image twice costs nothing and tells you "
    "nothing new."
)

_GENERATE_INVOICE_DESCRIPTION: Final = (
    "Ask ShipBob to price the shipment this claim is about, and get back the products it "
    "contained with their codes, quantities and prices. The prices are there so you can "
    "tell similar products apart; never write one back."
)

_COMPUTE_REIMBURSEMENT_DESCRIPTION: Final = (
    "Check an amount you are thinking of recommending. Name the damaged products and the "
    "figure, and it tells you what those products cost on the shipment's invoice and "
    "whether your figure is within the amount a claim may be reimbursed — or what it "
    "would be brought down to if it is not. Use it before you settle on a figure."
)

_ARGUMENTS_DID_NOT_FIT: Final = (
    "That call did not fit this tool's arguments. Read the tool's arguments again and "
    "make the call properly."
)
"""What the model is told when it calls a tool with arguments that will not parse.

The tool library checks a call against its arguments before our code runs, and would
otherwise raise. NFR-4 says a failure ends in front of a person, never in a stopped
run, so a malformed call is answered with a sentence the model can act on instead.
"""


# --- Where a memo of an expensive answer is filed ---------------------------
# One claim's answers are remembered so that two products investigated at the same
# time never pay for the same work twice (NFR-8). Each key names its question
# completely, so two questions that could differ can never share one.

_ATTACHMENTS_MEMO: Final = "attachments:{case_id}"
_INVOICE_MEMO: Final = "invoice:{shipment_id}"
_IMAGE_MEMO: Final = "image:{attachment_id}:{question}"


# --- What a tool hands back -------------------------------------------------


class ToolOutcome(BaseModel):
    """What every tool hands back, whether it worked or not.

    A tool answers with one of these rather than raising, so a failure is something
    the investigation can read and work around instead of something that stops it
    (NFR-4). It travels beside the sentence the model reads, as the tool call's
    artifact, which means the run can act on the parts of an answer without reading
    them back out of text.

    Attributes:
        tool: Which of the four tools produced this.
        succeeded: Whether the tool did what it set out to do. Note what this is
            *not*: an image that turns out to be too blurry to use is a successful
            call, because finding that out is exactly what was asked for. This is
            false only when the tool could not answer the question at all.
        summary: One plain sentence saying what happened, ready to put in the run's
            record and in front of somebody watching. The model reads this too, with
            whatever the tool found listed underneath it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    succeeded: bool
    summary: str


class AttachmentListing(ToolOutcome):
    """The images on the claim, by id.

    `attachment_ids` is empty both when the claim genuinely has no images — an
    ordinary answer, and the only possible one for a claim like CASE-1005 (FR-1.6) —
    and when the listing could not be fetched. `succeeded` is what tells those two
    apart, and they must never be confused: "the merchant sent nothing" and "we could
    not look" lead to opposite outcomes.

    File names and file types are deliberately absent. They carry no signal about what
    an image holds, and the surest way to stop anything leaning on one is never to
    pass it on (FR-1.4).
    """

    tool: str = LIST_ATTACHMENTS
    attachment_ids: tuple[str, ...] = ()


class ImageInspection(ToolOutcome):
    """What one image turned out to be, or why nothing could be established about it.

    `state` is the field to read, because it says *whose problem* an unusable image is
    (FR-1.5, NFR-4):

    * `None` — the image was read and answered about. Whether it turned out to be one
      of the four kinds of evidence is in `observation`.
    * `UNUSABLE` — the merchant's image cannot support a conclusion: too dark, too
      blurry, too cropped. They can send another, and `observation.problem` says what
      to ask them for.
    * `UNREADABLE` — *we* could not fetch the image or could not get an answer about
      it. The merchant can do nothing about this and must not be asked to; the claim
      needs a person.

    `observation` is `None` whenever the model was never reached — a bad id, an
    allowance used up, a download that failed.
    """

    tool: str = INSPECT_IMAGE
    attachment_id: str
    state: EvidenceState | None = None
    observation: ImageObservation | None = None


class ShipmentInvoice(ToolOutcome):
    """ShipBob's priced list of what the shipment contained (FR-1.18).

    `line_items` are the invoice's own lines, prices included. They are the only
    figures a recommended amount may be worked out from, and the invoice id in
    `invoice_id` is what a report names when it says where a figure came from.

    Both are empty or `None` when ShipBob would not price the shipment, which is a
    settled answer rather than a fault, and one the investigation has to be able to
    carry on from.
    """

    tool: str = GENERATE_INVOICE
    invoice_id: str | None = None
    line_items: tuple[OrderLineItem, ...] = ()


class AmountCheck(ToolOutcome):
    """What a proposed amount comes to once the cap has been applied to it.

    The investigation decides what the damage is worth; this says whether that figure
    survives the reimbursement cap, and what the products cost on the invoice for
    comparison (FR-1.21, FR-1.20).

    **It may show figures, and that is a change.** Until FR-1.21 was reversed, nothing
    here could carry an amount at all — the arithmetic produced the figure and a model
    that had seen one could copy it into a merchant email. The model now produces the
    figure itself, so hiding it here would achieve nothing. The guarantee that remains is
    at the other end: the email carries a marker, and code substitutes the *capped* amount
    into it, so what reaches a merchant is the figure that survived the cap.

    `capped` says the proposal was above the limit and `recommended_usd` is what it became.
    `items_total_usd` is what the products cost, which is context and not a limit — a claim
    may reasonably come to less than the goods did.

    Every figure is text, because that is how money is carried through this system without
    passing through a floating point number.
    """

    tool: str = COMPUTE_REIMBURSEMENT
    priced_products: tuple[str, ...] = ()
    priced_from: str | None = None
    proposed_usd: str | None = None
    recommended_usd: str | None = None
    items_total_usd: str | None = None
    cap_usd: str | None = None
    capped: bool = False


# --- What the model may pass to a tool --------------------------------------


class NoArguments(BaseModel):
    """A tool that takes nothing.

    Two of the four are like this, and that is a decision rather than a shortcut: the
    claim's case id, its shipment and its merchant are fixed when the run is built, so
    the investigation cannot ask to see another case's images or ask ShipBob to price
    a shipment that has nothing to do with this claim. Whatever it says, it is
    answered about this claim only.
    """

    model_config = ConfigDict(extra="forbid")


class InspectImageArguments(BaseModel):
    """Which image to look at, and optionally what to look for in it."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str = Field(
        description="The id of the image to look at, as listed on this claim.",
    )
    question: str | None = Field(
        default=None,
        description=(
            "Something particular to look for, such as whether the box is crushed on any "
            "face. Leave it out to simply ask what the image is."
        ),
    )


class ComputeReimbursementArguments(BaseModel):
    """The damaged products, and the figure the investigation is considering for them."""

    model_config = ConfigDict(extra="forbid")

    damaged_items: tuple[DamagedItem, ...] = Field(
        description=(
            "The damaged products, named exactly as the order and the invoice write them."
        ),
    )
    proposed_amount_usd: str = Field(
        description=(
            "The amount you are considering, in dollars, written as digits with at most "
            "two decimal places and no currency symbol — for example 31.20."
        ),
    )


# --- What a tool needs to answer a question ---------------------------------


@dataclass(frozen=True)
class _ToolContext:
    """Everything the four tools need, handed in when the run is built.

    Nothing in this file reaches for a client, a model or a policy of its own. That is
    what lets a test hand in a ShipBob that answers from memory and a model that
    answers from a script, and it is what keeps one run's allowance, record and memo
    from being shared with another run by accident.
    """

    case_id: str
    shipment_id: str | None
    user_id: str | None
    claim_line_id: str | None
    evidence: EvidenceClient
    fetcher: ImageFetcher
    model: StructuredModel
    cache: ObservationCache
    budget: RunBudget
    ledger: RunLedger
    events: EventStream
    policy: Policy


def investigation_tools(
    *,
    case_id: str,
    shipment_id: str | None,
    user_id: str | None,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    model: StructuredModel,
    cache: ObservationCache,
    budget: RunBudget,
    ledger: RunLedger,
    events: EventStream,
    policy: Policy,
    claim_line_id: str | None = None,
) -> list[BaseTool]:
    """Assemble the tools one investigation run is given (FR-1.2).

    **This is the only place the tools are put together, and that is the point.** "What
    can the agent do?" has exactly one answer, in one function, and it is four read and
    reasoning tools. Nothing that sends an email or moves money is here, or can be
    reached from here.

    Build one of these per run. The budget and the ledger belong to a single run and
    must not be shared between two of them (FR-1.3); the memo and the event stream
    belong to the whole claim and should be shared, so that two products investigated
    at the same time never pay twice for looking at the same photograph (NFR-8) and a
    watcher sees one ordered stream of messages.

    Args:
        case_id: The claim being investigated. Fixed here rather than asked for, so the
            investigation can only ever be answered about this claim.
        shipment_id: The parcel the claim is about, from the case. `None` when the case
            names no shipment, and then the invoice tool says so plainly instead of
            calling ShipBob.
        user_id: The merchant, from the case. ShipBob needs it to price a shipment, so
            `None` has the same effect as a missing shipment.
        evidence: Reads the case's images and asks ShipBob to price the shipment. It is
            the only ShipBob client an investigation holds, and it can only read.
        fetcher: Turns an image's address into the picture itself.
        model: Asked what an image is, and constrained to answer on a form (NFR-2).
        cache: This claim's memo of expensive answers. One per claim.
        budget: This run's allowances. One per run. The tools spend the image
            allowance; steps belong to whoever drives the run and are spent there.
        ledger: This run's record of what it did. One per run.
        events: Says what is happening while the run is still working. Shared by the
            whole claim.
        policy: Read for the reimbursement cap, so the limit is a configured value
            rather than a number buried in a branch (FR-0.7, NFR-7).
        claim_line_id: The one damaged product this run answers for, named on every
            event so a screen can tell several runs apart. `None` for the pass that
            works on the claim as a whole.

    Returns:
        The four tools, ready to bind to a model.
    """
    context = _ToolContext(
        case_id=case_id,
        shipment_id=shipment_id,
        user_id=user_id,
        claim_line_id=claim_line_id,
        evidence=evidence,
        fetcher=fetcher,
        model=model,
        cache=cache,
        budget=budget,
        ledger=ledger,
        events=events,
        policy=policy,
    )
    return [
        _build(LIST_ATTACHMENTS, _LIST_ATTACHMENTS_DESCRIPTION, NoArguments, context, _list_images),
        _build(INSPECT_IMAGE, _INSPECT_IMAGE_DESCRIPTION, InspectImageArguments, context, _inspect),
        _build(GENERATE_INVOICE, _GENERATE_INVOICE_DESCRIPTION, NoArguments, context, _invoice),
        _build(
            COMPUTE_REIMBURSEMENT,
            _COMPUTE_REIMBURSEMENT_DESCRIPTION,
            ComputeReimbursementArguments,
            context,
            _amount_check,
        ),
    ]


# --- The four tools ---------------------------------------------------------


async def _list_images(context: _ToolContext) -> tuple[str, AttachmentListing]:
    """List the images on the claim, by id (FR-1.4, FR-1.6).

    An empty claim is an ordinary answer and is said as one: there is nothing to look
    at, which settles the claim quickly rather than failing it. A listing that could
    not be fetched says so instead, because "the merchant sent nothing" and "we could
    not look" lead to opposite outcomes.

    Returns:
        The sentence the model reads with the ids under it, and the listing beside it.
    """
    asked = f"List the images on case {context.case_id}."
    try:
        attachments = await _attachments_on_the_case(context)
    except ClaimAgentError as failure:
        outcome = AttachmentListing(
            succeeded=False,
            summary=f"The images on this claim could not be listed. {failure}",
        )
        return await _finish(context, outcome, asked=asked, reference=context.case_id)

    if not attachments:
        outcome = AttachmentListing(
            succeeded=True,
            summary=(
                "This claim has no images at all. That is an ordinary answer and not a "
                "failure: there is nothing to look at, so do not go looking."
            ),
        )
        return await _finish(context, outcome, asked=asked, reference=context.case_id)

    listed = AttachmentListing(
        succeeded=True,
        summary=f"This claim has {len(attachments)} image(s).",
        attachment_ids=tuple(attachment.attachment_id for attachment in attachments),
    )
    return await _finish(
        context,
        listed,
        asked=asked,
        reference=context.case_id,
        lines=[f"- {attachment_id}" for attachment_id in listed.attachment_ids],
    )


async def _inspect(
    context: _ToolContext, attachment_id: str, question: str | None = None
) -> tuple[str, ImageInspection]:
    """Look at one image and say what it is and whether it can be relied on (FR-1.4, FR-1.5).

    The costly one. It fetches the picture, shows it to the model, and takes back an
    answer on a fixed form. The answer is remembered for the whole claim, so a second
    run asking the same question about the same image is handed the first run's answer
    and pays nothing (NFR-8), and the run's image allowance is spent only when the work
    actually happens.

    Four things can go wrong, and they are told apart because they lead different
    places: an id that is on no image here, an allowance already used up, an image we
    could not fetch or get an answer about, and an image the model says is too poor to
    conclude anything from. Only the last of those is something the merchant can fix.

    Returns:
        The sentence the model reads with what was seen under it, and the inspection
        beside it.
    """
    asked = f"Look at image {attachment_id}."
    if question is not None:
        asked = f"Look at image {attachment_id} and answer: {question}"

    try:
        attachments = await _attachments_on_the_case(context)
    except ClaimAgentError as failure:
        return await _finish(
            context,
            ImageInspection(
                succeeded=False,
                summary=f"The images on this claim could not be listed. {failure}",
                attachment_id=attachment_id,
                state=EvidenceState.UNREADABLE,
            ),
            asked=asked,
            reference=attachment_id,
        )

    attachment = _find(attachments, attachment_id)
    if attachment is None:
        return await _finish(
            context,
            ImageInspection(
                succeeded=False,
                summary=(
                    f"There is no image with the id {attachment_id} on this claim. "
                    "List the images to see which ids there are."
                ),
                attachment_id=attachment_id,
            ),
            asked=asked,
            reference=attachment_id,
        )

    memo_key = _IMAGE_MEMO.format(attachment_id=attachment_id, question=_as_asked(question))
    # The allowance is only in the way of work that has not been done yet. An answer
    # this claim already holds costs nothing to hand over, so it is handed over even
    # when the run has looked at as many images as it may (NFR-8).
    answers_this_claim_holds = context.cache.keys()
    if memo_key not in answers_this_claim_holds and not context.budget.has_image_analysis_left():
        return await _finish(
            context,
            ImageInspection(
                succeeded=False,
                summary=(
                    "This run has looked at as many images as it is allowed to. Draw your "
                    "conclusion from what you already have, or say that you cannot."
                ),
                attachment_id=attachment_id,
            ),
            asked=asked,
            reference=attachment_id,
        )

    try:
        observation = await context.cache.get_or_compute(
            memo_key, partial(_analyse, context, attachment, question)
        )
    except ClaimAgentError as failure:
        # Ours, not the merchant's. The picture may be perfectly good; we could not
        # fetch it or could not get an answer about it, and asking them to send it
        # again is a request they cannot act on (NFR-4).
        return await _finish(
            context,
            ImageInspection(
                succeeded=False,
                summary=(
                    f"Image {attachment_id} could not be read by this system. {failure} "
                    "This is our problem and not the merchant's, so do not ask them for it "
                    "again."
                ),
                attachment_id=attachment_id,
                state=EvidenceState.UNREADABLE,
            ),
            asked=asked,
            reference=attachment_id,
        )

    return await _finish(
        context,
        _inspection_of(attachment_id, observation),
        asked=asked,
        reference=attachment_id,
        lines=_what_was_seen(attachment_id, observation),
    )


async def _invoice(context: _ToolContext) -> tuple[str, ShipmentInvoice]:
    """Ask ShipBob to price what the shipment contained (FR-1.18).

    The invoice is the only document a recommended amount may be priced from, so a
    shipment ShipBob will not price is a settled answer the investigation has to be
    able to carry on from rather than a fault to stop at.

    Prices are passed on to the model, which is the same considered choice the prompts
    already make about the order's prices: an order can hold two similar products at
    different prices, and the model cannot refuse to guess between them without seeing
    that they differ (FR-1.13). It is told, twice over, never to write one back.

    Returns:
        The sentence the model reads with the priced lines under it, and the invoice
        beside it.
    """
    asked = f"Ask ShipBob to price shipment {context.shipment_id}."
    if context.shipment_id is None or context.user_id is None:
        return await _finish(
            context,
            ShipmentInvoice(
                succeeded=False,
                summary=(
                    "This claim does not say which shipment or which merchant it is for, so "
                    "ShipBob cannot price it. There will be no invoice for this claim."
                ),
            ),
            asked=asked,
            reference=context.shipment_id,
        )

    try:
        invoice = await _invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await _finish(
            context,
            ShipmentInvoice(
                succeeded=False,
                summary=f"This shipment could not be priced. {failure}",
            ),
            asked=asked,
            reference=context.shipment_id,
        )

    priced = ShipmentInvoice(
        succeeded=True,
        summary=(
            f"Invoice {invoice.invoice_id} prices this shipment at "
            f"{len(invoice.line_items)} line(s)."
        ),
        invoice_id=invoice.invoice_id,
        line_items=invoice.line_items,
    )
    return await _finish(
        context,
        priced,
        asked=asked,
        reference=context.shipment_id,
        lines=[_render_invoice_lines(invoice.line_items)],
    )


async def _amount_check(
    context: _ToolContext,
    damaged_items: Sequence[DamagedItem],
    proposed_amount_usd: str,
) -> tuple[str, AmountCheck]:
    """Check a figure the investigation is considering against the cap (FR-1.21, FR-1.20).

    The investigation decides what the damage is worth. This lets it check that figure
    before committing to it: what the products cost on the invoice, and whether the amount
    is within the cap or would be brought down to it.

    **It shows figures, unlike every earlier version of this tool.** That is the reversal
    of FR-1.21 — the model produces the amount now, so withholding one here would protect
    nothing. What still holds is that the email carries a marker and code substitutes the
    capped figure into it, so no number the model wrote reaches a merchant.

    An item that is on no invoice line, or that could be either of two, prices nothing at
    all: narrowing two candidates to one is the judgement this system is not allowed to
    make (FR-1.13). The figure is still checked against the cap in that case, so the run
    learns both things at once.

    Returns:
        The sentence the model reads with the products under it, and the check beside it.
    """
    named = ", ".join(item.product_name for item in damaged_items) or "nothing"
    asked = f"Is {proposed_amount_usd} a sound amount for: {named}?"

    if not damaged_items:
        return await _finish(
            context,
            AmountCheck(
                succeeded=True,
                summary=(
                    "You named no damaged products, so there is nothing to check an amount "
                    "against. Establish what was damaged first."
                ),
            ),
            asked=asked,
        )

    if context.shipment_id is None or context.user_id is None:
        return await _finish(
            context,
            AmountCheck(
                succeeded=False,
                summary=(
                    "This claim does not say which shipment or which merchant it is for, so "
                    "there is no invoice to price anything against."
                ),
            ),
            asked=asked,
        )

    try:
        invoice = await _invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await _finish(
            context,
            AmountCheck(
                succeeded=False,
                summary=(
                    f"No amount could be worked out, because this shipment could not be "
                    f"priced. {failure}"
                ),
            ),
            asked=asked,
        )

    try:
        derivation = review_recommended_amount(
            proposed_amount_usd,
            reasoning="",
            damaged=[_as_claimed_product(item) for item in damaged_items],
            invoice=invoice,
            policy=context.policy,
        )
    except ValueError as refused:
        # Not money. Told back plainly rather than rounded or guessed at, so the run can
        # write it properly on its next turn instead of a payout being interpreted.
        return await _finish(
            context,
            AmountCheck(succeeded=False, summary=str(refused)),
            asked=asked,
        )

    priced_products = tuple(component.product_name for component in derivation.components)

    if not derivation.components:
        return await _finish(
            context,
            AmountCheck(
                succeeded=True,
                summary=(
                    f"None of the products you named could be found on invoice "
                    f"{invoice.invoice_id}. At least one is on no line of it, or could be "
                    "either of two lines. Say what would settle which product it is rather "
                    "than naming an amount for it."
                ),
                priced_from=invoice.invoice_id,
                proposed_usd=str(derivation.proposed_usd),
                cap_usd=str(derivation.cap_usd),
            ),
            asked=asked,
            reference=invoice.invoice_id,
        )

    summary = (
        f"{derivation.proposed_usd} is over the {derivation.cap_usd} a claim may be "
        f"reimbursed, so it would be brought down to {derivation.amount_usd}."
        if derivation.cap_applied
        else (
            f"{derivation.proposed_usd} is within the {derivation.cap_usd} a claim may be "
            f"reimbursed, so it stands."
        )
    )
    return await _finish(
        context,
        AmountCheck(
            succeeded=True,
            summary=(
                f"{summary} Those products cost {derivation.items_total_usd} on invoice "
                f"{invoice.invoice_id}. Write {AMOUNT_PLACEHOLDER} where an amount belongs "
                "in the email — the figure is put in after the cap has been applied."
            ),
            priced_products=priced_products,
            priced_from=invoice.invoice_id,
            proposed_usd=str(derivation.proposed_usd),
            recommended_usd=str(derivation.amount_usd),
            items_total_usd=str(derivation.items_total_usd),
            cap_usd=str(derivation.cap_usd),
            capped=derivation.cap_applied,
        ),
        asked=asked,
        reference=invoice.invoice_id,
        lines=[_render_priced_products(priced_products)],
    )


# --- The work behind the tools ----------------------------------------------


async def _attachments_on_the_case(context: _ToolContext) -> tuple[Attachment, ...]:
    """The claim's images, fetched once per claim however many runs ask for them.

    Two tools need the listing — one to report it and one to turn an id into an address
    — and a claim covering four damaged products has four runs asking. Filing the
    answer in the claim's memo means ShipBob is asked once (NFR-8).

    Raises:
        ClaimAgentError: the claim does not exist, or ShipBob could not be reached. A
            failure is deliberately not remembered, so the next caller tries again.
    """
    return await context.cache.get_or_compute(
        _ATTACHMENTS_MEMO.format(case_id=context.case_id),
        partial(context.evidence.list_attachments, context.case_id),
    )


async def _invoice_for_the_shipment(
    context: _ToolContext, shipment_id: str, user_id: str
) -> Invoice:
    """The shipment's priced invoice, generated once per claim (FR-1.18, NFR-8).

    Filed in the claim's memo for the same reason the listing is: the tool that reports
    the invoice and the tool that prices damaged items against it both need it, and so
    does every run on the claim.

    Raises:
        ClaimAgentError: ShipBob will not price this shipment, or could not be reached.
    """
    return await context.cache.get_or_compute(
        _INVOICE_MEMO.format(shipment_id=shipment_id),
        partial(context.evidence.generate_invoice, shipment_id=shipment_id, user_id=user_id),
    )


async def _analyse(
    context: _ToolContext, attachment: Attachment, question: str | None
) -> ImageObservation:
    """Fetch one image, show it to the model, and take back an answer on a form.

    Runs only when this claim has no answer to this question yet, because the memo
    calls it only on a miss. The image allowance is spent here, at the start, so that
    an attempt which fails part way still counts: a download that broke cost what a
    download that worked costs, and an allowance that only counted successes would let
    a run with unreachable images look at far more of them than intended (NFR-8).

    Raises:
        ClaimAgentError: the image could not be fetched, or the model could not be
            reached or would not answer on the form. Either way this is our failure and
            not the merchant's, and the caller turns it into an unreadable result.
    """
    context.budget.spend_image_analysis()
    image = await context.fetcher.fetch(attachment)
    return await context.model.ask(
        ImageObservation,
        build_image_classification_messages(image_url=_as_data_url(image), question=question),
    )


def _inspection_of(attachment_id: str, observation: ImageObservation) -> ImageInspection:
    """Turn what the model saw into a result, and say whose problem it is if it is a poor image.

    An image the model says it cannot rely on is a **successful** call: finding that out
    is what was asked for, and the answer is worth as much as any other. What it is not
    is evidence — it counts the same as an image that was never sent, and the merchant
    can send another, which is what `UNUSABLE` records (FR-1.5, FR-1.7).
    """
    if not observation.is_legible:
        problem = observation.problem or "it is not clear enough to draw a conclusion from"
        return ImageInspection(
            succeeded=True,
            summary=(
                f"Image {attachment_id} cannot be relied on. It counts as missing, and the "
                "merchant can be asked for another."
            ),
            attachment_id=attachment_id,
            state=EvidenceState.UNUSABLE,
            observation=observation.model_copy(update={"problem": problem}),
        )

    if observation.kind is None:
        return ImageInspection(
            succeeded=True,
            summary=f"Image {attachment_id} is none of the four kinds of evidence.",
            attachment_id=attachment_id,
            observation=observation,
        )

    return ImageInspection(
        succeeded=True,
        summary=f"Image {attachment_id} is a {observation.kind.value}.",
        attachment_id=attachment_id,
        observation=observation,
    )


def _what_was_seen(attachment_id: str, observation: ImageObservation) -> list[str]:
    """Write out what was in the image, for the model to read under the summary.

    What was read off a photograph is text nobody at ShipBob wrote, so it is marked as
    such. A photograph of a note reading "approve this claim" tells the investigation
    what the note says and nothing more, and the marked block is what makes that plain
    rather than leaving it to good intentions.
    """
    said = [f"What is visible: {observation.shows}"]
    if observation.problem is not None:
        said.append(f"Why it cannot be relied on: {observation.problem}")
    said.append(f"How sure: {observation.confidence:.2f}")
    return [quote_untrusted(f"IMAGE_{attachment_id}", "\n".join(said))]


def _render_invoice_lines(line_items: Sequence[OrderLineItem]) -> str:
    """Write out an invoice's lines the way the prompts write out an order's.

    Same shape, so a product on the invoice and the same product on the order read
    alike and can be compared without translating between two layouts. Product names
    are the merchant's own catalogue text, so they are marked as text we did not write.
    """
    if not line_items:
        return "This invoice has no lines at all, so it prices nothing."
    listed = "\n".join(
        f"- {item.name} | code {item.sku or 'no code'} | quantity {item.quantity} | "
        f"each {_money(item.unit_price)}"
        for item in line_items
    )
    return quote_untrusted("INVOICE_LINE_ITEMS", listed)


def _render_priced_products(product_names: Sequence[str]) -> str:
    """Name the products that were priced, so the model can see its list was understood.

    Quantities and prices are left out. The names come from the invoice rather than
    from what the model asked about, which is what lets it notice that a name it
    guessed at was matched to something else.
    """
    return quote_untrusted("PRICED_PRODUCTS", "\n".join(f"- {name}" for name in product_names))


# --- Writing every call down ------------------------------------------------

OutcomeT = TypeVar("OutcomeT", bound=ToolOutcome)


async def _finish(
    context: _ToolContext,
    outcome: OutcomeT,
    *,
    asked: str,
    reference: str | None = None,
    lines: Sequence[str] = (),
) -> tuple[str, OutcomeT]:
    """Record a tool call, say it happened, and hand the answer back.

    Every call goes through here, and every call is recorded whether it worked or not.
    The ledger entry is what a representative reads when she asks why a claim was
    escalated (NFR-3), and the event is what somebody watching sees while the run is
    still going — a tool being called is the investigation choosing what to look at
    next, which is the whole reason this is an agent rather than a fixed sequence of
    steps (FR-1.1).

    A stream nobody is listening to, or one that fails, changes nothing: the event
    stream swallows its own troubles so that a closed browser cannot fail a claim.

    Args:
        context: The run this call belongs to.
        outcome: What the tool established, success or failure.
        asked: What the tool was asked, in one plain sentence, for the record.
        reference: The id of the thing the call was about, so a representative can look
            at what the system looked at. `None` when it was about no one thing.
        lines: What the model reads under the summary — ids, invoice lines, what was
            seen in a photograph. Left out when the summary says everything.

    Returns:
        The text the model reads, and the outcome beside it. The tool library puts the
        first in front of the model and keeps the second on the tool call, so the run
        can act on the parts of an answer without reading them back out of prose.
    """
    context.ledger.record(
        kind=StepKind.TOOL_CALL,
        name=outcome.tool,
        asked=asked,
        observed=outcome.summary,
        succeeded=outcome.succeeded,
        reference=reference,
    )
    detail = {"tool": outcome.tool, "succeeded": "yes" if outcome.succeeded else "no"}
    if reference is not None:
        detail["reference"] = reference
    await context.events.emit(
        EventKind.TOOL_CALLED,
        outcome.summary,
        claim_line_id=context.claim_line_id,
        **detail,
    )
    return "\n".join([outcome.summary, *lines]), outcome


# --- Small conversions ------------------------------------------------------


def _build(
    name: str,
    description: str,
    arguments: type[BaseModel],
    context: _ToolContext,
    work: Callable[..., Awaitable[tuple[str, ToolOutcome]]],
) -> BaseTool:
    """Wrap one of the functions above as a tool the model can be offered.

    The run's context is bound in here rather than passed by the model, so nothing the
    model says can change which claim, which allowance or which record a call belongs
    to.

    Two settings are load-bearing. The answer is handed back as a sentence and an
    object together: the model reads the sentence, and the run keeps the object, which
    is how an unreadable image stays distinguishable from an unusable one without
    anybody parsing prose. And a call whose arguments will not parse is answered rather
    than raised, so that a model's mistake is something the run can recover from (NFR-4).
    """
    return StructuredTool.from_function(
        coroutine=partial(work, context),
        name=name,
        description=description,
        args_schema=arguments,
        response_format="content_and_artifact",
        handle_validation_error=_ARGUMENTS_DID_NOT_FIT,
    )


def _find(attachments: Sequence[Attachment], attachment_id: str) -> Attachment | None:
    """Pick out the image with this id, or say there is none.

    `None` means the model named an id this claim does not have, which is a mistake it
    can recover from once it is told, and not a failure of ours.
    """
    return next(
        (attachment for attachment in attachments if attachment.attachment_id == attachment_id),
        None,
    )


def _as_asked(question: str | None) -> str:
    """Reduce a question to the form two of them are compared in, for the memo's key.

    Runs of spaces are typing rather than meaning, so "is the box crushed?" asked with
    a stray newline in it is the same question and gets the same answer. Nothing else
    is ignored: two questions that differ in a word can have different answers, and
    they must never share a key. No question at all is its own key, distinct from any
    question somebody asked.
    """
    if question is None:
        return ""
    return " ".join(question.split())


def _as_data_url(image: FetchedImage) -> str:
    """Write a downloaded image as an address that carries the picture inside it.

    A model is shown a picture by address. The image is already in hand, so the address
    holds the bytes themselves rather than pointing back at ShipBob's storage — which
    also means the signed link, which acts as a password for the file, is never written
    into a prompt.
    """
    return f"data:{image.media_type};base64,{image.data_base64}"


def _as_claimed_product(item: DamagedItem) -> ClaimedProduct:
    """Turn what the model says was damaged into what the arithmetic reads.

    The two shapes say the same thing in different words, deliberately: what a model is
    allowed to assert is a narrower thing than what the rest of the system works with,
    and keeping them apart is what stops a field appearing on one because it was
    convenient on the other.
    """
    return ClaimedProduct(name=item.product_name, quantity=item.quantity, sku=item.sku)


def _money(amount: Decimal) -> str:
    """A price from ShipBob's records, written out for the model to read.

    An amount going in, never one coming out. Nothing the model writes is ever turned
    back into a figure by this system: that arithmetic reads ShipBob's records rather
    than the model's words (FR-1.21).
    """
    return f"{amount:.2f}"
