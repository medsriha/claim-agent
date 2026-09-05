"""Everything an investigation can do, and the one place it is all assembled (FR-1.2).

Read-only by construction: sending email and paying a merchant live in
`claim_agent.execution`, which nothing in this package imports. Adding a writing tool here
would delete that guarantee. A tool never raises into the investigation either — every
failure comes back as an ordinary result the model can reason about (NFR-4).
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
from claim_agent.agent.schemas import DamagedItem, ImageObservation
from claim_agent.domain.case_facts import read_case_facts
from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.currency import convert_to_usd, currency_for_claim
from claim_agent.domain.document_money import check_document_arithmetic, parse_money_text
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.evidence_integrity import find_duplicate_evidence
from claim_agent.domain.evidence_sufficiency import assess_evidence_sufficiency
from claim_agent.domain.item_matching import match_items
from claim_agent.domain.models import Attachment, Case, Invoice, OrderLineItem, Shipment
from claim_agent.domain.price_reconciliation import (
    LineMatchKind,
    PriceReconciliation,
    ReceiptLine,
    reconcile_prices,
)
from claim_agent.domain.reimbursement import review_recommended_amount
from claim_agent.domain.remedy import classify_remedy
from claim_agent.errors import ClaimAgentError
from claim_agent.policy import Policy
from claim_agent.shipbob.evidence_client import EvidenceClient

# --- What the tools are called ---------------------------------------------

LIST_ATTACHMENTS: Final = "list_attachments"
INSPECT_IMAGE: Final = "inspect_image"
GENERATE_INVOICE: Final = "generate_invoice"
COMPUTE_REIMBURSEMENT: Final = "compute_reimbursement"
CHECK_CURRENCY: Final = "check_currency"
CHECK_DOCUMENT_TOTALS: Final = "check_document_totals"
READ_CASE_FACTS: Final = "read_case_facts"
COMPARE_PRICES: Final = "compare_prices"
CHECK_EVIDENCE_IS_ENOUGH: Final = "check_evidence_is_enough"
MATCH_DAMAGED_PRODUCT: Final = "match_damaged_product"
READ_REQUESTED_REMEDY: Final = "read_requested_remedy"

# Every tool an investigation has, in one tuple, so the surface can be checked at a glance.
TOOL_NAMES: Final = (
    LIST_ATTACHMENTS,
    INSPECT_IMAGE,
    GENERATE_INVOICE,
    COMPUTE_REIMBURSEMENT,
    CHECK_CURRENCY,
    CHECK_DOCUMENT_TOTALS,
    READ_CASE_FACTS,
    COMPARE_PRICES,
    CHECK_EVIDENCE_IS_ENOUGH,
    MATCH_DAMAGED_PRODUCT,
    READ_REQUESTED_REMEDY,
)

# --- What the model is told each tool does ---------------------------------
# These sentences are read by the model, so they say what a tool answers and what
# it costs, and nothing about how it works.

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

_CHECK_CURRENCY_DESCRIPTION: Final = (
    "Find out what currency this claim's money is in, and turn an amount into dollars. "
    "ShipBob's records never say what currency a price is in, and the amount a claim may "
    "be reimbursed is a dollar figure — so a price that is really in pounds is measured "
    "against the wrong limit unless you check. Tell it any currency symbols you have seen "
    "on the evidence. Call it before you settle on an amount, on any claim where the "
    "parcel or the paperwork looks like it came from outside the United States."
)

_CHECK_DOCUMENT_TOTALS_DESCRIPTION: Final = (
    "Check whether an invoice or receipt you have read agrees with itself. Give it the "
    "line amounts and whatever totals the document printed, exactly as they are written "
    "on it, and it adds them up again and tells you where the document contradicts "
    "itself. Do not do this arithmetic yourself — a total on a photograph is a claim the "
    "document makes, not a fact, and one of these documents is wrong."
)

_READ_CASE_FACTS_DESCRIPTION: Final = (
    "Read the facts written into this claim's own description — the damage type, the "
    "defect type, how many orders it says are affected, the carrier and the last tracking "
    "date — and compare them with ShipBob's records. It tells you where the two "
    "disagree. Those disagreements matter: the description and the shipment record name "
    "different carriers on most claims."
)

_COMPARE_PRICES_DESCRIPTION: Final = (
    "Compare what ShipBob says the shipment was worth against what the customer's own "
    "receipt says they paid. Give it the lines you read off the receipt. The two disagree "
    "on every sample claim, sometimes by a lot, and it will not tell you which is right — "
    "that is for a person to decide. Use it whenever the merchant has sent an invoice or "
    "an order screen."
)

_CHECK_EVIDENCE_IS_ENOUGH_DESCRIPTION: Final = (
    "Say whether the evidence on this claim can support a recommendation at all. Tell it "
    "what you found for each of the four kinds of evidence. It answers with what is still "
    "missing and the exact sentence to ask the merchant for each one — and it separates "
    "what the merchant can fix from what only a person here can. It also tells you if the "
    "same photograph has been attached to this claim twice."
)

_MATCH_DAMAGED_PRODUCT_DESCRIPTION: Final = (
    "Find which lines on the shipment's invoice could be the damaged product, with a score "
    "and a reason for each. Product names differ between ShipBob and a merchant's own "
    "paperwork, so an exact match often fails when the product is obviously the same. If "
    "two lines score alike it says so and picks neither — that is for a person."
)

_READ_REQUESTED_REMEDY_DESCRIPTION: Final = (
    "Work out what the merchant actually asked for — money back, a replacement, a spare "
    "part, or the order sent again. Give it their own words. One sample claim asks for a "
    "replacement lid, which no reimbursement answers. It says 'unclear' rather than "
    "guessing, and it is a second opinion on your own reading, not a replacement for it."
)

# What the model is told when it calls a tool with arguments that will not parse.
_ARGUMENTS_DID_NOT_FIT: Final = (
    "That call did not fit this tool's arguments. Read the tool's arguments again and "
    "make the call properly."
)

# One claim's answers are remembered so two products investigated at the same time never
# pay for the same work twice (NFR-8). Each key names its question completely.

_ATTACHMENTS_MEMO: Final = "attachments:{case_id}"
_INVOICE_MEMO: Final = "invoice:{shipment_id}"
_IMAGE_MEMO: Final = "image:{attachment_id}:{question}"


# --- What a tool hands back -------------------------------------------------


class ToolOutcome(BaseModel):
    """What every tool hands back, whether it worked or not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    succeeded: bool
    summary: str


class AttachmentListing(ToolOutcome):
    """The images on the claim, by id."""

    tool: str = LIST_ATTACHMENTS
    attachment_ids: tuple[str, ...] = ()


class ImageInspection(ToolOutcome):
    """What one image turned out to be, or why nothing could be established about it."""

    tool: str = INSPECT_IMAGE
    attachment_id: str
    state: EvidenceState | None = None
    observation: ImageObservation | None = None


class ShipmentInvoice(ToolOutcome):
    """ShipBob's priced list of what the shipment contained (FR-1.18)."""

    tool: str = GENERATE_INVOICE
    invoice_id: str | None = None
    line_items: tuple[OrderLineItem, ...] = ()


class AmountCheck(ToolOutcome):
    """What a proposed amount comes to once the cap has been applied to it."""

    tool: str = COMPUTE_REIMBURSEMENT
    priced_products: tuple[str, ...] = ()
    priced_from: str | None = None
    proposed_usd: str | None = None
    recommended_usd: str | None = None
    items_total_usd: str | None = None
    cap_usd: str | None = None
    capped: bool = False


class CurrencyCheck(ToolOutcome):
    """What currency this claim's money is in, and an amount turned into dollars."""

    tool: str = CHECK_CURRENCY
    currency: str | None = None
    is_ambiguous: bool = False
    confidence: float = 0.0
    original_amount: str | None = None
    usd_amount: str | None = None
    rate_used: str | None = None
    rates_as_of: str | None = None
    assumed_usd: bool = False


class DocumentTotalsCheck(ToolOutcome):
    """Whether a document a merchant sent adds up on its own terms."""

    tool: str = CHECK_DOCUMENT_TOTALS
    line_total: str | None = None
    is_consistent: bool = True
    disagreements: tuple[str, ...] = ()
    unreadable_figures: tuple[str, ...] = ()


class CaseFactsReading(ToolOutcome):
    """The facts written into the claim's own description, and where they contradict ShipBob."""

    tool: str = READ_CASE_FACTS
    damage_type: str | None = None
    defect_type: str | None = None
    affected_order_count: int | None = None
    described_carrier: str | None = None
    contradictions: tuple[str, ...] = ()
    could_not_read: tuple[str, ...] = ()


class PriceComparison(ToolOutcome):
    """How ShipBob's prices compare with the prices on the customer's own receipt."""

    tool: str = COMPARE_PRICES
    shipbob_total: str | None = None
    receipt_total: str | None = None
    total_difference: str | None = None
    totals_diverge: bool = False
    line_counts_differ: bool = False
    findings: tuple[str, ...] = ()


class EvidenceSufficiency(ToolOutcome):
    """Whether the evidence on this claim can support a recommendation."""

    tool: str = CHECK_EVIDENCE_IS_ENOUGH
    is_supportable: bool = False
    missing: tuple[str, ...] = ()
    requests: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    needs_rep_clarification: bool = False
    repeated_images: tuple[str, ...] = ()


class ProductMatches(ToolOutcome):
    """Which invoice lines could be the damaged product, and how sure each is."""

    tool: str = MATCH_DAMAGED_PRODUCT
    candidates: tuple[str, ...] = ()
    is_ambiguous: bool = False


class RemedyRequested(ToolOutcome):
    """What the merchant asked for, in their own words."""

    tool: str = READ_REQUESTED_REMEDY
    remedies: tuple[str, ...] = ()
    reason: str | None = None


# --- What the model may pass to a tool --------------------------------------


class ReceiptLineArgument(BaseModel):
    """One priced line the investigation read off a customer's receipt."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="The product, as the receipt writes it.")
    amount: str = Field(
        description=(
            "What this line came to on the receipt, written as digits with at most two "
            "decimal places and no currency symbol — for example 16.99. A credit or "
            "discount goes in with a minus in front."
        ),
    )
    sku: str | None = Field(default=None, description="The product's code on the receipt, or null.")
    quantity: int | None = Field(default=None, description="How many, if the receipt says.")


class CheckCurrencyArguments(BaseModel):
    """Any currency symbols seen, and optionally an amount to turn into dollars."""

    model_config = ConfigDict(extra="forbid")

    symbols_seen: tuple[str, ...] = Field(
        default=(),
        description=(
            "Currency symbols you have actually seen on this claim's evidence, such as "
            "£ or $. This is the strongest clue there is, because it is the only one "
            "where somebody wrote the currency down. Leave it out if you have seen none."
        ),
    )
    amount: str | None = Field(
        default=None,
        description=(
            "An amount to turn into dollars, written as digits with at most two decimal "
            "places and no currency symbol. Leave it out to just ask which currency."
        ),
    )


class CheckDocumentTotalsArguments(BaseModel):
    """The figures printed on one document, exactly as the document writes them."""

    model_config = ConfigDict(extra="forbid")

    line_amounts: tuple[str, ...] = Field(
        description=(
            "What each item on the document costs, as the document writes it — keep the "
            "currency symbol and any commas, so '£1,234.56' goes in exactly like that."
        ),
    )
    subtotal: str | None = Field(default=None, description="The subtotal it printed, or null.")
    tax: str | None = Field(default=None, description="The tax it printed, or null.")
    shipping: str | None = Field(default=None, description="The shipping it printed, or null.")
    discount: str | None = Field(
        default=None,
        description="The discount it printed, as a positive figure, or null.",
    )
    total: str | None = Field(default=None, description="The grand total it printed, or null.")


class ComparePricesArguments(BaseModel):
    """The lines read off the customer's receipt, and the total it printed."""

    model_config = ConfigDict(extra="forbid")

    receipt_lines: tuple[ReceiptLineArgument, ...] = Field(
        description="The priced lines on the receipt, in the order they are printed.",
    )
    receipt_total: str | None = Field(
        default=None,
        description=(
            "The total the receipt printed, if it printed one. Give it even when it "
            "disagrees with the lines — a receipt with a discount or tax usually does."
        ),
    )


class EvidenceFindingArgument(BaseModel):
    """What was found for one of the four kinds of evidence."""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind = Field(description="Which kind of evidence this is about.")
    state: EvidenceState = Field(
        description=(
            "Whether it is present, missing, unusable because the merchant's own image "
            "cannot support a conclusion, or unreadable because we could not read it."
        ),
    )
    observed: str = Field(default="", description="What you actually saw, in one sentence.")
    attachment_id: str | None = Field(default=None, description="Which image, if any.")
    problem: str | None = Field(default=None, description="What is wrong with it, if anything.")


class CheckEvidenceArguments(BaseModel):
    """What was found for each of the four kinds of evidence."""

    model_config = ConfigDict(extra="forbid")

    findings: tuple[EvidenceFindingArgument, ...] = Field(
        description="One entry per kind of evidence you have reached a view on.",
    )


class MatchProductArguments(BaseModel):
    """The damaged product, as the merchant or the order names it."""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(description="The product's name, however it is written.")
    sku: str | None = Field(default=None, description="Its code, if you have one.")
    quantity: int = Field(default=1, ge=1, description="How many were damaged.")


class ReadRemedyArguments(BaseModel):
    """The merchant's own words about what they want done."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="What the merchant wrote, quoted as closely as you can.")


class NoArguments(BaseModel):
    """A tool that takes nothing."""

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
    """Everything the investigation tools need, handed in when the run is built."""

    case_id: str
    shipment_id: str | None
    user_id: str | None
    claim_line_id: str | None
    case: Case | None
    shipment: Shipment | None
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
    case: Case | None = None,
    shipment: Shipment | None = None,
) -> list[BaseTool]:
    """Assemble the tools one investigation run is given (FR-1.2)."""
    context = _ToolContext(
        case_id=case_id,
        shipment_id=shipment_id,
        user_id=user_id,
        claim_line_id=claim_line_id,
        case=case,
        shipment=shipment,
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
        _build(
            CHECK_CURRENCY,
            _CHECK_CURRENCY_DESCRIPTION,
            CheckCurrencyArguments,
            context,
            _currency_check,
        ),
        _build(
            CHECK_DOCUMENT_TOTALS,
            _CHECK_DOCUMENT_TOTALS_DESCRIPTION,
            CheckDocumentTotalsArguments,
            context,
            _document_totals_check,
        ),
        _build(READ_CASE_FACTS, _READ_CASE_FACTS_DESCRIPTION, NoArguments, context, _case_facts),
        _build(
            COMPARE_PRICES,
            _COMPARE_PRICES_DESCRIPTION,
            ComparePricesArguments,
            context,
            _price_comparison,
        ),
        _build(
            CHECK_EVIDENCE_IS_ENOUGH,
            _CHECK_EVIDENCE_IS_ENOUGH_DESCRIPTION,
            CheckEvidenceArguments,
            context,
            _evidence_is_enough,
        ),
        _build(
            MATCH_DAMAGED_PRODUCT,
            _MATCH_DAMAGED_PRODUCT_DESCRIPTION,
            MatchProductArguments,
            context,
            _match_product,
        ),
        _build(
            READ_REQUESTED_REMEDY,
            _READ_REQUESTED_REMEDY_DESCRIPTION,
            ReadRemedyArguments,
            context,
            _requested_remedy,
        ),
    ]


# --- Tool implementations --------------------------------------------------


async def _list_images(context: _ToolContext) -> tuple[str, AttachmentListing]:
    """List the images on the claim, by id (FR-1.4, FR-1.6)."""
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
    """Look at one image and say what it is and whether it can be relied on (FR-1.4, FR-1.5)."""
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
    """Ask ShipBob to price what the shipment contained (FR-1.18)."""
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
    """Check a figure the investigation is considering against the cap (FR-1.21, FR-1.20)."""
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
                f"{invoice.invoice_id}. Do not write an amount or placeholder in the email — "
                "the capped figure is added after you answer."
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


async def _currency_check(
    context: _ToolContext,
    symbols_seen: tuple[str, ...] = (),
    amount: str | None = None,
) -> tuple[str, CurrencyCheck]:
    """Say what currency this claim's money is in, and put an amount into dollars."""
    asked = "What currency is this claim's money in?"
    finding = currency_for_claim(
        tracking_number=context.shipment.tracking_number if context.shipment else None,
        carrier=context.shipment.carrier if context.shipment else None,
        symbols_seen=symbols_seen,
    )

    if amount is None:
        return await _finish(
            context,
            CurrencyCheck(
                succeeded=True,
                summary=finding.reason,
                currency=finding.currency,
                is_ambiguous=finding.is_ambiguous,
                confidence=finding.confidence,
            ),
            asked=asked,
        )

    written = parse_money_text(amount)
    if written is None:
        return await _finish(
            context,
            CurrencyCheck(
                succeeded=False,
                summary=(
                    f"{quote_untrusted('amount', amount)} could not be read as an amount, so nothing "
                    "was converted. Write it as digits with at most two decimal places."
                ),
                currency=finding.currency,
                is_ambiguous=finding.is_ambiguous,
                confidence=finding.confidence,
            ),
            asked=asked,
        )

    converted = convert_to_usd(written.amount, finding.currency, context.policy)
    return await _finish(
        context,
        CurrencyCheck(
            succeeded=True,
            summary=f"{finding.reason} {converted.summary}",
            currency=finding.currency,
            is_ambiguous=finding.is_ambiguous,
            confidence=finding.confidence,
            original_amount=converted.original_amount,
            usd_amount=converted.usd_amount,
            rate_used=converted.rate_used,
            rates_as_of=converted.rates_as_of,
            assumed_usd=converted.assumed_usd,
        ),
        asked=asked,
    )


async def _document_totals_check(
    context: _ToolContext,
    line_amounts: tuple[str, ...],
    subtotal: str | None = None,
    tax: str | None = None,
    shipping: str | None = None,
    discount: str | None = None,
    total: str | None = None,
) -> tuple[str, DocumentTotalsCheck]:
    """Add a document's own figures up again and report where it contradicts itself."""
    asked = "Does this document add up?"
    unreadable: list[str] = []

    def read(written: str | None) -> Decimal | None:
        """Read one figure, remembering the ones that could not be read exactly."""
        if written is None:
            return None
        parsed = parse_money_text(written)
        if parsed is None:
            unreadable.append(written)
            return None
        return parsed.amount

    amounts = [value for value in (read(one) for one in line_amounts) if value is not None]
    check = check_document_arithmetic(
        amounts,
        subtotal=read(subtotal),
        tax=read(tax),
        shipping=read(shipping),
        discount=read(discount),
        total=read(total),
        policy=context.policy,
    )

    refused = tuple(quote_untrusted("figure", one) for one in unreadable)
    note = (
        ""
        if not refused
        else f" {len(refused)} figure(s) could not be read exactly and were left out."
    )
    disagreements = tuple(one.explanation for one in check.discrepancies)
    if check.nothing_to_check:
        summary = (
            f"The items on this document add up to {_money(check.line_total)}. It prints no "
            "totals of its own, so there was nothing to check that against."
        )
    elif check.adds_up:
        summary = (
            f"This document adds up. Its items come to {_money(check.line_total)} and its "
            "printed totals agree."
        )
    else:
        summary = (
            f"This document does not agree with itself in {len(disagreements)} place(s). "
            "Treat any figure read off it with care."
        )

    return await _finish(
        context,
        DocumentTotalsCheck(
            succeeded=True,
            summary=summary + note,
            line_total=_money(check.line_total),
            is_consistent=check.adds_up,
            disagreements=disagreements,
            unreadable_figures=refused,
        ),
        asked=asked,
        lines=list(disagreements),
    )


async def _case_facts(context: _ToolContext) -> tuple[str, CaseFactsReading]:
    """Read the facts written into the claim's own description, and check them."""
    asked = "What does this claim's own description say, and does it match ShipBob's records?"

    if context.case is None:
        return await _finish(
            context,
            CaseFactsReading(
                succeeded=False,
                summary="This claim's case record is not in hand, so its description cannot be read.",
            ),
            asked=asked,
        )

    facts = read_case_facts(context.case, context.shipment)
    contradictions = tuple(
        f"The description says {one.described}, but ShipBob's records say {one.recorded}. "
        f"{one.why_it_matters}"
        for one in facts.contradictions
    )
    summary = (
        "This claim's description agrees with ShipBob's records as far as it goes."
        if not contradictions
        else f"This claim's description disagrees with ShipBob's records in {len(contradictions)} "
        "place(s)."
    )
    return await _finish(
        context,
        CaseFactsReading(
            succeeded=True,
            summary=summary,
            damage_type=facts.damage_type,
            defect_type=facts.defect_type,
            affected_order_count=facts.affected_order_count,
            described_carrier=facts.carrier,
            contradictions=contradictions,
            could_not_read=facts.unreadable,
        ),
        asked=asked,
        reference=context.case.case_id,
        lines=list(contradictions),
    )


async def _price_comparison(
    context: _ToolContext,
    receipt_lines: tuple[ReceiptLineArgument, ...],
    receipt_total: str | None = None,
) -> tuple[str, PriceComparison]:
    """Compare ShipBob's prices with the prices on the customer's own receipt."""
    asked = "Do ShipBob's prices agree with the customer's receipt?"

    if context.shipment_id is None or context.user_id is None:
        return await _finish(
            context,
            PriceComparison(
                succeeded=False,
                summary=(
                    "This claim does not say which shipment or which merchant it is for, so "
                    "there is no ShipBob pricing to compare a receipt against."
                ),
            ),
            asked=asked,
        )

    try:
        invoice = await _invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await _finish(
            context,
            PriceComparison(
                succeeded=False,
                summary=f"This shipment could not be priced, so there is nothing to compare. {failure}",
            ),
            asked=asked,
        )

    unreadable: list[str] = []
    lines: list[ReceiptLine] = []
    for one in receipt_lines:
        written = parse_money_text(one.amount)
        if written is None:
            unreadable.append(one.amount)
            continue
        lines.append(
            ReceiptLine(
                description=one.description,
                sku=one.sku,
                quantity=one.quantity,
                amount=written.amount,
            )
        )

    printed_total = parse_money_text(receipt_total) if receipt_total is not None else None
    comparison = reconcile_prices(
        invoice.line_items,
        lines,
        policy=context.policy,
        receipt_total=printed_total.amount if printed_total else None,
    )

    note = (
        ""
        if not unreadable
        else f" {len(unreadable)} receipt figure(s) could not be read exactly and were left out."
    )
    findings = _comparison_findings(comparison)
    return await _finish(
        context,
        PriceComparison(
            succeeded=True,
            summary=comparison.summary + note,
            shipbob_total=_money(comparison.shipbob_total),
            receipt_total=_money(comparison.receipt_total),
            total_difference=_money(comparison.total_difference),
            totals_diverge=comparison.totals_diverge,
            line_counts_differ=comparison.line_counts_differ,
            findings=findings,
        ),
        asked=asked,
        reference=invoice.invoice_id,
        lines=list(findings),
    )


async def _evidence_is_enough(
    context: _ToolContext,
    findings: tuple[EvidenceFindingArgument, ...],
) -> tuple[str, EvidenceSufficiency]:
    """Say whether this claim's evidence can support a recommendation at all."""
    asked = "Is there enough evidence on this claim to recommend anything?"
    assessment = assess_evidence_sufficiency(
        [
            EvidenceFinding(
                kind=one.kind,
                state=one.state,
                observed=one.observed,
                attachment_id=one.attachment_id,
                problem=one.problem,
            )
            for one in findings
        ]
    )

    attachments = await _attachments_on_the_case(context)
    duplicates = find_duplicate_evidence(
        attachments, {one.attachment_id: context.case_id for one in attachments}
    )
    repeated = tuple(
        f"{' and '.join(group.attachment_ids)} are the same photograph."
        for group in duplicates.within_claim_groups
    )

    return await _finish(
        context,
        EvidenceSufficiency(
            succeeded=True,
            summary=assessment.reason,
            is_supportable=assessment.is_supportable,
            missing=tuple(one.value for one in assessment.missing_or_unusable),
            requests=assessment.requests,
            unreadable=tuple(one.value for one in assessment.unreadable),
            needs_rep_clarification=assessment.needs_rep_clarification,
            repeated_images=repeated,
        ),
        asked=asked,
        lines=[*assessment.requests, *repeated],
    )


async def _match_product(
    context: _ToolContext,
    product_name: str,
    sku: str | None = None,
    quantity: int = 1,
) -> tuple[str, ProductMatches]:
    """Find which invoice lines could be the damaged product, and how sure each is."""
    asked = f"Which invoice lines could be {product_name}?"

    if context.shipment_id is None or context.user_id is None:
        return await _finish(
            context,
            ProductMatches(
                succeeded=False,
                summary="This claim names no shipment or merchant, so there is no invoice to match against.",
            ),
            asked=asked,
        )

    try:
        invoice = await _invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await _finish(
            context,
            ProductMatches(
                succeeded=False,
                summary=f"This shipment could not be priced, so there is nothing to match against. {failure}",
            ),
            asked=asked,
        )

    matches = match_items(
        ClaimedProduct(name=product_name, quantity=quantity, sku=sku),
        invoice.line_items,
        context.policy,
    )
    if not matches:
        return await _finish(
            context,
            ProductMatches(
                succeeded=True,
                summary=(
                    f"Nothing on invoice {invoice.invoice_id} looks enough like "
                    f"{quote_untrusted('product', product_name)} to offer as a match."
                ),
            ),
            asked=asked,
            reference=invoice.invoice_id,
        )

    ambiguous = any(one.is_ambiguous for one in matches)
    candidates = tuple(one.explanation for one in matches)
    summary = (
        f"{len(matches)} line(s) on invoice {invoice.invoice_id} could be this product, and "
        "two of them score alike — say what would settle which it is rather than choosing."
        if ambiguous
        else f"{len(matches)} line(s) on invoice {invoice.invoice_id} could be this product."
    )
    return await _finish(
        context,
        ProductMatches(
            succeeded=True, summary=summary, candidates=candidates, is_ambiguous=ambiguous
        ),
        asked=asked,
        reference=invoice.invoice_id,
        lines=list(candidates),
    )


async def _requested_remedy(context: _ToolContext, text: str) -> tuple[str, RemedyRequested]:
    """Work out what the merchant actually asked to happen."""
    reading = classify_remedy(text)
    return await _finish(
        context,
        RemedyRequested(
            succeeded=True,
            summary=reading.reason,
            remedies=tuple(one.kind.value for one in reading.requested),
            reason=reading.reason,
        ),
        asked="What did the merchant ask for?",
    )


# --- The work behind the tools ----------------------------------------------


def _comparison_findings(comparison: PriceReconciliation) -> tuple[str, ...]:
    """The differences worth naming to the model, one plain sentence each."""
    named: list[str] = []
    for line in comparison.lines:
        if line.kind is LineMatchKind.AMBIGUOUS:
            named.append(
                f"{line.description} could be more than one line on the other document, so "
                "nothing was compared for it."
            )
        elif line.kind is LineMatchKind.SHIPBOB_ONLY:
            named.append(f"{line.description} is on ShipBob's records but not on the receipt.")
        elif line.kind is LineMatchKind.RECEIPT_ONLY:
            named.append(f"{line.description} is on the receipt but not on ShipBob's records.")
        elif line.diverges:
            named.append(
                f"{line.description} is {_money(line.shipbob_amount or Decimal(0))} on "
                f"ShipBob's records and {_money(line.receipt_amount or Decimal(0))} on the "
                "receipt."
            )
    return tuple(named)


async def _attachments_on_the_case(context: _ToolContext) -> tuple[Attachment, ...]:
    """The claim's images, fetched once per claim however many runs ask for them."""
    return await context.cache.get_or_compute(
        _ATTACHMENTS_MEMO.format(case_id=context.case_id),
        partial(context.evidence.list_attachments, context.case_id),
    )


async def _invoice_for_the_shipment(
    context: _ToolContext, shipment_id: str, user_id: str
) -> Invoice:
    """The shipment's priced invoice, generated once per claim (FR-1.18, NFR-8)."""
    return await context.cache.get_or_compute(
        _INVOICE_MEMO.format(shipment_id=shipment_id),
        partial(context.evidence.generate_invoice, shipment_id=shipment_id, user_id=user_id),
    )


async def _analyse(
    context: _ToolContext, attachment: Attachment, question: str | None
) -> ImageObservation:
    """Fetch one image, show it to the model, and take back an answer on a form."""
    context.budget.spend_image_analysis()
    image = await context.fetcher.fetch(attachment)
    return await context.model.ask(
        ImageObservation,
        build_image_classification_messages(image_url=_as_data_url(image), question=question),
    )


def _inspection_of(attachment_id: str, observation: ImageObservation) -> ImageInspection:
    """Turn what the model saw into a result, and say whose problem it is if it is a poor image."""
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
    """Write out what was in the image, for the model to read under the summary."""
    said = [f"What is visible: {observation.shows}"]
    if observation.problem is not None:
        said.append(f"Why it cannot be relied on: {observation.problem}")
    return [quote_untrusted(f"IMAGE_{attachment_id}", "\n".join(said))]


def _render_invoice_lines(line_items: Sequence[OrderLineItem]) -> str:
    """Write out an invoice's lines the way the prompts write out an order's."""
    if not line_items:
        return "This invoice has no lines at all, so it prices nothing."
    listed = "\n".join(
        f"- {item.name} | code {item.sku or 'no code'} | quantity {item.quantity} | "
        f"each {_money(item.unit_price)}"
        for item in line_items
    )
    return quote_untrusted("INVOICE_LINE_ITEMS", listed)


def _render_priced_products(product_names: Sequence[str]) -> str:
    """Name the products that were priced, so the model can see its list was understood."""
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
    """Record a tool call, say it happened, and hand the answer back."""
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
    """Wrap one of the functions above as a tool the model can be offered."""
    return StructuredTool.from_function(
        coroutine=partial(work, context),
        name=name,
        description=description,
        args_schema=arguments,
        response_format="content_and_artifact",
        handle_validation_error=_ARGUMENTS_DID_NOT_FIT,
    )


def _find(attachments: Sequence[Attachment], attachment_id: str) -> Attachment | None:
    """Pick out the image with this id, or say there is none."""
    return next(
        (attachment for attachment in attachments if attachment.attachment_id == attachment_id),
        None,
    )


def _as_asked(question: str | None) -> str:
    """Reduce a question to the form two of them are compared in, for the memo's key."""
    if question is None:
        return ""
    return " ".join(question.split())


def _as_data_url(image: FetchedImage) -> str:
    """Write a downloaded image as an address that carries the picture inside it."""
    return f"data:{image.media_type};base64,{image.data_base64}"


def _as_claimed_product(item: DamagedItem) -> ClaimedProduct:
    """Turn what the model says was damaged into what the arithmetic reads."""
    return ClaimedProduct(name=item.product_name, quantity=item.quantity, sku=item.sku)


def _money(amount: Decimal) -> str:
    """A price from ShipBob's records, written out for the model to read."""
    return f"{amount:.2f}"
