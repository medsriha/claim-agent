"""The tools a run is offered: what each is called, what the model is told about it, assembly."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Final

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.tools import checking, reading
from claim_agent.agent.tools._shared import (
    ARGUMENTS_DID_NOT_FIT,
    CHECK_CURRENCY,
    CHECK_DOCUMENT_TOTALS,
    CHECK_EVIDENCE_IS_ENOUGH,
    COMPARE_PRICES,
    COMPUTE_REIMBURSEMENT,
    GENERATE_INVOICE,
    INSPECT_IMAGE,
    LIST_ATTACHMENTS,
    MATCH_DAMAGED_PRODUCT,
    READ_CASE_FACTS,
    READ_REQUESTED_REMEDY,
    TOOL_NAMES,
    TRIAGE_TOOL_NAMES,
    AmountCheck,
    AttachmentClassification,
    AttachmentListing,
    CaseFactsReading,
    CheckCurrencyArguments,
    CheckDocumentTotalsArguments,
    CheckEvidenceArguments,
    ComparePricesArguments,
    ComputeReimbursementArguments,
    CurrencyCheck,
    DocumentTotalsCheck,
    EvidenceFindingArgument,
    EvidenceSufficiency,
    ImageInspection,
    ImageLog,
    InspectImageArguments,
    MatchProductArguments,
    NoArguments,
    PriceComparison,
    ProductMatches,
    ReadRemedyArguments,
    ReceiptLineArgument,
    RemedyRequested,
    ShipmentInvoice,
    ToolContext,
    ToolOutcome,
)
from claim_agent.domain.models import Case, Shipment
from claim_agent.policy import Policy
from claim_agent.shipbob.evidence_client import EvidenceClient

__all__ = [
    "CHECK_CURRENCY",
    "CHECK_DOCUMENT_TOTALS",
    "CHECK_EVIDENCE_IS_ENOUGH",
    "COMPARE_PRICES",
    "COMPUTE_REIMBURSEMENT",
    "GENERATE_INVOICE",
    "INSPECT_IMAGE",
    "LIST_ATTACHMENTS",
    "MATCH_DAMAGED_PRODUCT",
    "READ_CASE_FACTS",
    "READ_REQUESTED_REMEDY",
    "TOOL_NAMES",
    "TRIAGE_TOOL_NAMES",
    "AmountCheck",
    "AttachmentClassification",
    "AttachmentListing",
    "CaseFactsReading",
    "CheckCurrencyArguments",
    "CheckDocumentTotalsArguments",
    "CheckEvidenceArguments",
    "ComparePricesArguments",
    "ComputeReimbursementArguments",
    "CurrencyCheck",
    "DocumentTotalsCheck",
    "EvidenceFindingArgument",
    "EvidenceSufficiency",
    "ImageInspection",
    "ImageLog",
    "InspectImageArguments",
    "MatchProductArguments",
    "NoArguments",
    "PriceComparison",
    "ProductMatches",
    "ReadRemedyArguments",
    "ReceiptLineArgument",
    "RemedyRequested",
    "ShipmentInvoice",
    "ToolOutcome",
    "investigation_tools",
]


_DESCRIPTIONS: Final[dict[str, str]] = {
    LIST_ATTACHMENTS: (
        "List the images on this claim. You get their ids and nothing else. A claim with no "
        "images at all is an ordinary answer and not a failure."
    ),
    INSPECT_IMAGE: (
        "Look at one image on this claim and say what it is and whether it can be relied on. "
        "This is the most expensive thing you can do, and there is a limit on how many images "
        "one run may look at. Asking about the same image twice costs nothing and tells you "
        "nothing new."
    ),
    GENERATE_INVOICE: (
        "Ask ShipBob to price the shipment this claim is about, and get back the products it "
        "contained with their codes, quantities and prices. The prices are there so you can "
        "tell similar products apart; never write one back."
    ),
    COMPUTE_REIMBURSEMENT: (
        "Check an amount you are thinking of recommending. Name the damaged products and the "
        "figure, and it tells you what those products cost on the shipment's invoice and "
        "whether your figure is within the amount a claim may be reimbursed — or what it "
        "would be brought down to if it is not. Use it before you settle on a figure."
    ),
    CHECK_CURRENCY: (
        "Find out what currency this claim's money is in, and turn an amount into dollars. "
        "ShipBob's records never say what currency a price is in, and the amount a claim may "
        "be reimbursed is a dollar figure, so a price in another currency is measured against "
        "the wrong limit unless you check. Tell it any currency symbols you have seen on the "
        "evidence. Call it before you settle on an amount, on any claim where the parcel or "
        "the paperwork looks like it came from outside the United States."
    ),
    CHECK_DOCUMENT_TOTALS: (
        "Check whether an invoice or receipt you have read agrees with itself. Give it the "
        "line amounts and whatever totals the document printed, exactly as they are written "
        "on it, and it adds them up again and tells you where the document contradicts "
        "itself. Do not do this arithmetic yourself: a total on a photograph is a claim the "
        "document makes, not a fact."
    ),
    READ_CASE_FACTS: (
        "Read the facts written into this claim's own description — the damage type, the "
        "defect type, how many orders it says are affected, the carrier and the last tracking "
        "date — and compare them with ShipBob's records. It tells you where the two disagree, "
        "which is worth knowing before you rely on either."
    ),
    COMPARE_PRICES: (
        "Compare what ShipBob says the shipment was worth against what the customer's own "
        "receipt says they paid. Give it the lines you read off the receipt. Where the two "
        "disagree it says so and by how much; it will not say which is right, because that is "
        "for a person to decide. Use it whenever the merchant has sent an invoice or an order "
        "screen."
    ),
    CHECK_EVIDENCE_IS_ENOUGH: (
        "Say whether the evidence on this claim can support a recommendation at all. Tell it "
        "what you found for each of the four kinds of evidence. It answers with what is still "
        "missing and the exact sentence to ask the merchant for each one — and it separates "
        "what the merchant can fix from what only a person here can. It also tells you if the "
        "same photograph has been attached to this claim twice."
    ),
    MATCH_DAMAGED_PRODUCT: (
        "Find which lines on the shipment's invoice could be the damaged product, with a score "
        "and a reason for each. Product names differ between ShipBob and a merchant's own "
        "paperwork, so an exact match often fails when the product is obviously the same. If "
        "two lines score alike it says so and picks neither — that is for a person."
    ),
    READ_REQUESTED_REMEDY: (
        "Work out what the merchant actually asked for — money back, a replacement, a spare "
        "part, or the order sent again. Give it their own words. A merchant who asked for a "
        "replacement part is not answered by a reimbursement, so it is worth knowing. It says "
        "'unclear' rather than guessing, and it is a second opinion on your own reading, not a "
        "replacement for it."
    ),
}

_Work = Callable[..., Awaitable[tuple[str, ToolOutcome]]]

_TOOLS: Final[dict[str, tuple[type[BaseModel], _Work]]] = {
    LIST_ATTACHMENTS: (NoArguments, reading.list_images),
    INSPECT_IMAGE: (InspectImageArguments, reading.inspect),
    GENERATE_INVOICE: (NoArguments, reading.invoice),
    COMPUTE_REIMBURSEMENT: (ComputeReimbursementArguments, checking.amount_check),
    CHECK_CURRENCY: (CheckCurrencyArguments, checking.currency_check),
    CHECK_DOCUMENT_TOTALS: (CheckDocumentTotalsArguments, checking.document_totals_check),
    READ_CASE_FACTS: (NoArguments, reading.case_facts),
    COMPARE_PRICES: (ComparePricesArguments, checking.price_comparison),
    CHECK_EVIDENCE_IS_ENOUGH: (CheckEvidenceArguments, checking.evidence_is_enough),
    MATCH_DAMAGED_PRODUCT: (MatchProductArguments, checking.match_product),
    READ_REQUESTED_REMEDY: (ReadRemedyArguments, reading.requested_remedy),
}


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
    case: Case | None = None,
    shipment: Shipment | None = None,
    names: Sequence[str] = TOOL_NAMES,
    images: ImageLog | None = None,
) -> list[BaseTool]:
    """Assemble the tools one run is given, in the fixed order (FR-1.2)."""
    unknown = set(names) - set(TOOL_NAMES)
    if unknown:
        raise ValueError(f"No such tool(s): {', '.join(sorted(unknown))}.")

    context = ToolContext(
        case_id=case_id,
        shipment_id=shipment_id,
        user_id=user_id,
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
        images=images,
    )
    wanted = set(names)
    return [_build(name, context) for name in TOOL_NAMES if name in wanted]


def _build(name: str, context: ToolContext) -> BaseTool:
    """Wrap one tool function so the model can be offered it."""
    arguments, work = _TOOLS[name]
    return StructuredTool.from_function(
        coroutine=partial(work, context),
        name=name,
        description=_DESCRIPTIONS[name],
        args_schema=arguments,
        response_format="content_and_artifact",
        handle_validation_error=ARGUMENTS_DID_NOT_FIT,
    )
