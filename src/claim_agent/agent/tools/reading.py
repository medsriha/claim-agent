"""Tools that read: the claim's images, its invoice, its description, and what was asked for."""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial

from claim_agent.agent.images import FetchedImage
from claim_agent.agent.prompts import build_image_classification_messages, quote_untrusted
from claim_agent.agent.schemas import ImageObservation
from claim_agent.agent.tools._shared import (
    ATTACHMENTS_MEMO,
    IMAGE_MEMO,
    INVOICE_MEMO,
    AttachmentListing,
    CaseFactsReading,
    ImageInspection,
    NoImageAnalysisLeftError,
    RemedyRequested,
    ShipmentInvoice,
    ToolContext,
    finish,
    money,
)
from claim_agent.domain.case_facts import read_case_facts
from claim_agent.domain.evidence import EvidenceState
from claim_agent.domain.models import Attachment, Invoice, OrderLineItem
from claim_agent.domain.remedy import classify_remedy
from claim_agent.errors import ClaimAgentError


async def list_images(context: ToolContext) -> tuple[str, AttachmentListing]:
    """List the images on the claim, by id (FR-1.4, FR-1.6)."""
    asked = f"List the images on case {context.case_id}."
    try:
        attachments = await attachments_on_the_case(context)
    except ClaimAgentError as failure:
        outcome = AttachmentListing(
            succeeded=False,
            summary=f"The images on this claim could not be listed. {failure}",
        )
        return await finish(context, outcome, asked=asked, reference=context.case_id)

    if not attachments:
        outcome = AttachmentListing(
            succeeded=True,
            summary=(
                "This claim has no images at all. That is an ordinary answer and not a "
                "failure: there is nothing to look at, so do not go looking."
            ),
        )
        return await finish(context, outcome, asked=asked, reference=context.case_id)

    listed = AttachmentListing(
        succeeded=True,
        summary=f"This claim has {len(attachments)} image(s).",
        attachment_ids=tuple(attachment.attachment_id for attachment in attachments),
    )
    return await finish(
        context,
        listed,
        asked=asked,
        reference=context.case_id,
        lines=[f"- {attachment_id}" for attachment_id in listed.attachment_ids],
    )


async def inspect(
    context: ToolContext, attachment_id: str, question: str | None = None
) -> tuple[str, ImageInspection]:
    """Look at one image and say what it is and whether it can be relied on (FR-1.4, FR-1.5)."""
    asked = f"Look at image {attachment_id}."
    if question is not None:
        asked = f"Look at image {attachment_id} and answer: {question}"

    try:
        attachments = await attachments_on_the_case(context)
    except ClaimAgentError as failure:
        return await _answer(
            context,
            ImageInspection(
                succeeded=False,
                summary=f"The images on this claim could not be listed. {failure}",
                attachment_id=attachment_id,
                state=EvidenceState.UNREADABLE,
            ),
            asked=asked,
        )

    attachment = _find(attachments, attachment_id)
    if attachment is None:
        return await _answer(
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
        )

    # The allowance is checked inside the memo's computation, so a cached answer costs
    # nothing and two images inspected at once cannot both pass one check (NFR-8).
    memo_key = IMAGE_MEMO.format(attachment_id=attachment_id, question=_as_asked(question))
    try:
        observation = await context.cache.get_or_compute(
            memo_key, partial(_analyse, context, attachment, question)
        )
    except NoImageAnalysisLeftError:
        return await _answer(
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
        )
    except ClaimAgentError as failure:
        # Ours, not the merchant's (NFR-4).
        return await _answer(
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
        )

    return await _answer(
        context,
        _inspection_of(attachment_id, observation),
        asked=asked,
        lines=_what_was_seen(attachment_id, observation),
    )


async def invoice(context: ToolContext) -> tuple[str, ShipmentInvoice]:
    """Ask ShipBob to price what the shipment contained (FR-1.18)."""
    asked = f"Ask ShipBob to price shipment {context.shipment_id}."
    if context.shipment_id is None or context.user_id is None:
        return await finish(
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
        priced = await invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await finish(
            context,
            ShipmentInvoice(
                succeeded=False, summary=f"This shipment could not be priced. {failure}"
            ),
            asked=asked,
            reference=context.shipment_id,
        )

    return await finish(
        context,
        ShipmentInvoice(
            succeeded=True,
            summary=(
                f"Invoice {priced.invoice_id} prices this shipment at "
                f"{len(priced.line_items)} line(s)."
            ),
            invoice_id=priced.invoice_id,
            line_items=priced.line_items,
        ),
        asked=asked,
        reference=context.shipment_id,
        lines=[_render_invoice_lines(priced.line_items)],
    )


async def case_facts(context: ToolContext) -> tuple[str, CaseFactsReading]:
    """Read the facts written into the claim's own description, and check them."""
    asked = "What does this claim's own description say, and does it match ShipBob's records?"

    if context.case is None:
        return await finish(
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
    return await finish(
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


async def requested_remedy(context: ToolContext, text: str) -> tuple[str, RemedyRequested]:
    """Work out what the merchant actually asked to happen."""
    reading = classify_remedy(text)
    return await finish(
        context,
        RemedyRequested(
            succeeded=True,
            summary=reading.reason,
            remedies=tuple(one.kind.value for one in reading.requested),
            reason=reading.reason,
        ),
        asked="What did the merchant ask for?",
    )


# --- Shared reads, done once per claim (NFR-8) ------------------------------


async def attachments_on_the_case(context: ToolContext) -> tuple[Attachment, ...]:
    """The claim's images, fetched once per claim however many calls ask."""
    return await context.cache.get_or_compute(
        ATTACHMENTS_MEMO.format(case_id=context.case_id),
        partial(context.evidence.list_attachments, context.case_id),
    )


async def invoice_for_the_shipment(context: ToolContext, shipment_id: str, user_id: str) -> Invoice:
    """The shipment's priced invoice, generated once per claim (FR-1.18)."""
    return await context.cache.get_or_compute(
        INVOICE_MEMO.format(shipment_id=shipment_id),
        partial(context.evidence.generate_invoice, shipment_id=shipment_id, user_id=user_id),
    )


# --- The work behind inspecting an image ------------------------------------


async def _answer(
    context: ToolContext,
    inspection: ImageInspection,
    *,
    asked: str,
    lines: Sequence[str] = (),
) -> tuple[str, ImageInspection]:
    """Finish an inspection and note what the image turned out to be."""
    answered = await finish(
        context, inspection, asked=asked, reference=inspection.attachment_id, lines=lines
    )
    if context.images is not None:
        await context.images.note(inspection)
    return answered


async def _analyse(
    context: ToolContext, attachment: Attachment, question: str | None
) -> ImageObservation:
    """Spend one analysis, fetch the image, and ask the model what it is."""
    if not context.budget.try_spend_image_analysis():
        raise NoImageAnalysisLeftError
    image = await context.fetcher.fetch(attachment)
    return await context.model.ask(
        ImageObservation,
        build_image_classification_messages(image_url=_as_data_url(image), question=question),
        on_usage=context.budget.record_usage,
    )


def _inspection_of(attachment_id: str, observation: ImageObservation) -> ImageInspection:
    """Turn what the model saw into an inspection, saying whose problem a poor image is."""
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
    """What was in the image, fenced as text we did not write."""
    said = [f"What is visible: {observation.shows}"]
    if observation.problem is not None:
        said.append(f"Why it cannot be relied on: {observation.problem}")
    return [quote_untrusted(f"IMAGE_{attachment_id}", "\n".join(said))]


def _render_invoice_lines(line_items: Sequence[OrderLineItem]) -> str:
    """An invoice's lines, written the way the prompts write an order's."""
    if not line_items:
        return "This invoice has no lines at all, so it prices nothing."
    listed = "\n".join(
        f"- {item.name} | code {item.sku or 'no code'} | quantity {item.quantity} | "
        f"each {money(item.unit_price)}"
        for item in line_items
    )
    return quote_untrusted("INVOICE_LINE_ITEMS", listed)


def _find(attachments: Sequence[Attachment], attachment_id: str) -> Attachment | None:
    """Pick out the image with this id, or say there is none."""
    return next(
        (attachment for attachment in attachments if attachment.attachment_id == attachment_id),
        None,
    )


def _as_asked(question: str | None) -> str:
    """Reduce a question to the form two of them are compared in, for the memo's key."""
    return "" if question is None else " ".join(question.split())


def _as_data_url(image: FetchedImage) -> str:
    """A downloaded image as an address that carries the picture inside it."""
    return f"data:{image.media_type};base64,{image.data_base64}"
