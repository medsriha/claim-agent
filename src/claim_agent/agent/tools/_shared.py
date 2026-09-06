"""What every tool module shares: names, outcomes, arguments, the run context, and the record."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.schemas import DamagedItem, ImageObservation
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.models import Case, OrderLineItem, Shipment
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

# The triage pass reads and identifies; it does not price or judge (FR-1a.1).
TRIAGE_TOOL_NAMES: Final = (
    LIST_ATTACHMENTS,
    INSPECT_IMAGE,
    READ_CASE_FACTS,
    MATCH_DAMAGED_PRODUCT,
)

# Every tool an investigation has.
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

# What the model is told when it calls a tool with arguments that will not parse.
ARGUMENTS_DID_NOT_FIT: Final = (
    "That call did not fit this tool's arguments. Read the tool's arguments again and "
    "make the call properly."
)

# Memo keys for the per-claim cache (NFR-8). Each names its question completely.
ATTACHMENTS_MEMO: Final = "attachments:{case_id}"
INVOICE_MEMO: Final = "invoice:{shipment_id}"
IMAGE_MEMO: Final = "image:{attachment_id}:{question}"


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


# --- What each image turned out to be, as the run looks at it (FR-1.4) --------


class AttachmentClassification(BaseModel):
    """What one image the run looked at turned out to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str
    kind: EvidenceKind | None = None
    state: EvidenceState
    observed: str
    problem: str | None = None


class ImageLog:
    """Every image a run has looked at, noted as it happens and announced on the stream.

    The triage pass reads this after its run to settle the claim's shared evidence. It
    replaces a callback that used to be attached to every tool: the inspect tool now
    writes here directly, which is plainer and survives tools running at the same time.
    """

    def __init__(self, events: EventStream) -> None:
        """Start an empty log that announces each image on `events`."""
        self._events = events
        self._seen: list[AttachmentClassification] = []

    async def note(self, inspection: ImageInspection) -> None:
        """Write down what one inspected image turned out to be, if anything was seen."""
        classified = classification_of(inspection)
        if classified is None:
            return
        self._seen.append(classified)
        await self._events.emit(
            EventKind.IMAGE_CLASSIFIED,
            what_the_image_was(classified),
            attachment_id=classified.attachment_id,
            evidence_kind="none" if classified.kind is None else classified.kind.value,
            state=classified.state.value,
        )

    def classifications(self) -> tuple[AttachmentClassification, ...]:
        """One entry per image, keeping a reading that named a kind over one that did not."""
        best: dict[str, AttachmentClassification] = {}
        for classified in self._seen:
            settled = best.get(classified.attachment_id)
            if settled is None or (settled.kind is None and classified.kind is not None):
                best[classified.attachment_id] = classified
        return tuple(best.values())


def classification_of(inspection: ImageInspection) -> AttachmentClassification | None:
    """What one inspection established about an image, or `None` when nothing was seen."""
    if inspection.state is EvidenceState.UNREADABLE:
        # Ours, not the merchant's: nothing was seen, only that we could not look (NFR-4).
        return AttachmentClassification(
            attachment_id=inspection.attachment_id,
            state=EvidenceState.UNREADABLE,
            observed="This image could not be read by this system.",
            problem=inspection.summary,
        )
    observation = inspection.observation
    if observation is None:
        return None
    return AttachmentClassification(
        attachment_id=inspection.attachment_id,
        kind=observation.kind,
        state=EvidenceState.UNUSABLE if not observation.is_legible else EvidenceState.PRESENT,
        observed=observation.shows,
        problem=observation.problem,
    )


def what_the_image_was(classified: AttachmentClassification) -> str:
    """One plain sentence about one image, for the screen."""
    if classified.state is EvidenceState.UNREADABLE:
        return f"Image {classified.attachment_id}: could not be read by this system."
    if classified.state is EvidenceState.UNUSABLE:
        return f"Image {classified.attachment_id}: too poor to rely on — {classified.problem}"
    if classified.kind is None:
        return f"Image {classified.attachment_id}: none of the four kinds of evidence."
    return f"Image {classified.attachment_id}: {classified.kind.value.replace('_', ' ')}."


# --- What a tool needs to answer a question ---------------------------------


@dataclass(frozen=True)
class ToolContext:
    """Everything the tools need, handed in when the run is built."""

    case_id: str
    shipment_id: str | None
    user_id: str | None
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
    images: ImageLog | None = field(default=None)


class NoImageAnalysisLeftError(Exception):
    """Raised inside the memo when the run may look at no more images.

    Not a `ClaimAgentError`: those read as "we could not read this image" and send the
    claim to a person. Running out of allowance is answered to the model in words.
    """


# --- Writing every call down ------------------------------------------------

OutcomeT = TypeVar("OutcomeT", bound=ToolOutcome)


async def finish(
    context: ToolContext,
    outcome: OutcomeT,
    *,
    asked: str,
    reference: str | None = None,
    lines: Sequence[str] = (),
) -> tuple[str, OutcomeT]:
    """Record a tool call, announce it, and hand the answer back as text plus artifact."""
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
    await context.events.emit(EventKind.TOOL_CALLED, outcome.summary, **detail)
    return "\n".join([outcome.summary, *lines]), outcome


def money(amount: Decimal) -> str:
    """A price from ShipBob's records, written out for the model to read."""
    return f"{amount:.2f}"
