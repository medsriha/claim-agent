"""Tools that check: a figure against the cap, a currency, a document's sums, a match."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from claim_agent.agent.prompts import quote_untrusted
from claim_agent.agent.schemas import DamagedItem
from claim_agent.agent.tools._shared import (
    AmountCheck,
    CurrencyCheck,
    DocumentTotalsCheck,
    EvidenceFindingArgument,
    EvidenceSufficiency,
    PriceComparison,
    ProductMatches,
    ReceiptLineArgument,
    ToolContext,
    finish,
    money,
)
from claim_agent.agent.tools.reading import attachments_on_the_case, invoice_for_the_shipment
from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.currency import convert_to_usd, currency_for_claim
from claim_agent.domain.document_money import check_document_arithmetic, parse_money_text
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.evidence_integrity import find_duplicate_evidence
from claim_agent.domain.evidence_sufficiency import assess_evidence_sufficiency
from claim_agent.domain.item_matching import match_items
from claim_agent.domain.price_reconciliation import (
    LineMatchKind,
    PriceReconciliation,
    ReceiptLine,
    reconcile_prices,
)
from claim_agent.domain.reimbursement import review_recommended_amount
from claim_agent.errors import ClaimAgentError

_NO_SHIPMENT = "This claim does not say which shipment or which merchant it is for, so "


async def amount_check(
    context: ToolContext,
    damaged_items: Sequence[DamagedItem],
    proposed_amount_usd: str,
) -> tuple[str, AmountCheck]:
    """Check a figure the investigation is considering against the cap (FR-1.21, FR-1.20)."""
    named = ", ".join(item.product_name for item in damaged_items) or "nothing"
    asked = f"Is {proposed_amount_usd} a sound amount for: {named}?"

    if not damaged_items:
        return await finish(
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
        return await finish(
            context,
            AmountCheck(
                succeeded=False,
                summary=_NO_SHIPMENT + "there is no invoice to price anything against.",
            ),
            asked=asked,
        )

    try:
        invoice = await invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await finish(
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
        return await finish(
            context, AmountCheck(succeeded=False, summary=str(refused)), asked=asked
        )

    priced_products = tuple(component.product_name for component in derivation.components)

    if not derivation.components:
        return await finish(
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
    return await finish(
        context,
        AmountCheck(
            succeeded=True,
            summary=(
                f"{summary} Those products cost {derivation.items_total_usd} on invoice "
                f"{invoice.invoice_id}. Do not write an amount in the email — the capped "
                "figure is added after you answer."
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
        lines=[quote_untrusted("PRICED_PRODUCTS", "\n".join(f"- {n}" for n in priced_products))],
    )


async def currency_check(
    context: ToolContext,
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
    found = {
        "currency": finding.currency,
        "is_ambiguous": finding.is_ambiguous,
        "confidence": finding.confidence,
    }

    if amount is None:
        return await finish(
            context, CurrencyCheck(succeeded=True, summary=finding.reason, **found), asked=asked
        )

    written = parse_money_text(amount)
    if written is None:
        return await finish(
            context,
            CurrencyCheck(
                succeeded=False,
                summary=(
                    f"{quote_untrusted('amount', amount)} could not be read as an amount, so nothing "
                    "was converted. Write it as digits with at most two decimal places."
                ),
                **found,
            ),
            asked=asked,
        )

    converted = convert_to_usd(written.amount, finding.currency, context.policy)
    return await finish(
        context,
        CurrencyCheck(
            succeeded=True,
            summary=f"{finding.reason} {converted.summary}",
            original_amount=converted.original_amount,
            usd_amount=converted.usd_amount,
            rate_used=converted.rate_used,
            rates_as_of=converted.rates_as_of,
            assumed_usd=converted.assumed_usd,
            **found,
        ),
        asked=asked,
    )


async def document_totals_check(
    context: ToolContext,
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
            f"The items on this document add up to {money(check.line_total)}. It prints no "
            "totals of its own, so there was nothing to check that against."
        )
    elif check.adds_up:
        summary = (
            f"This document adds up. Its items come to {money(check.line_total)} and its "
            "printed totals agree."
        )
    else:
        summary = (
            f"This document does not agree with itself in {len(disagreements)} place(s). "
            "Treat any figure read off it with care."
        )

    return await finish(
        context,
        DocumentTotalsCheck(
            succeeded=True,
            summary=summary + note,
            line_total=money(check.line_total),
            is_consistent=check.adds_up,
            disagreements=disagreements,
            unreadable_figures=refused,
        ),
        asked=asked,
        lines=list(disagreements),
    )


async def price_comparison(
    context: ToolContext,
    receipt_lines: tuple[ReceiptLineArgument, ...],
    receipt_total: str | None = None,
) -> tuple[str, PriceComparison]:
    """Compare ShipBob's prices with the prices on the customer's own receipt."""
    asked = "Do ShipBob's prices agree with the customer's receipt?"

    if context.shipment_id is None or context.user_id is None:
        return await finish(
            context,
            PriceComparison(
                succeeded=False,
                summary=_NO_SHIPMENT + "there is no ShipBob pricing to compare a receipt against.",
            ),
            asked=asked,
        )

    try:
        invoice = await invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await finish(
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
    return await finish(
        context,
        PriceComparison(
            succeeded=True,
            summary=comparison.summary + note,
            shipbob_total=money(comparison.shipbob_total),
            receipt_total=money(comparison.receipt_total),
            total_difference=money(comparison.total_difference),
            totals_diverge=comparison.totals_diverge,
            line_counts_differ=comparison.line_counts_differ,
            findings=findings,
        ),
        asked=asked,
        reference=invoice.invoice_id,
        lines=list(findings),
    )


async def evidence_is_enough(
    context: ToolContext,
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

    attachments = await attachments_on_the_case(context)
    duplicates = find_duplicate_evidence(
        attachments, {one.attachment_id: context.case_id for one in attachments}
    )
    repeated = tuple(
        f"{' and '.join(group.attachment_ids)} are the same photograph."
        for group in duplicates.within_claim_groups
    )

    return await finish(
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


async def match_product(
    context: ToolContext,
    product_name: str,
    sku: str | None = None,
    quantity: int = 1,
) -> tuple[str, ProductMatches]:
    """Find which invoice lines could be the damaged product, and how sure each is."""
    asked = f"Which invoice lines could be {product_name}?"

    if context.shipment_id is None or context.user_id is None:
        return await finish(
            context,
            ProductMatches(
                succeeded=False,
                summary=_NO_SHIPMENT + "there is no invoice to match against.",
            ),
            asked=asked,
        )

    try:
        invoice = await invoice_for_the_shipment(context, context.shipment_id, context.user_id)
    except ClaimAgentError as failure:
        return await finish(
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
        return await finish(
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
    return await finish(
        context,
        ProductMatches(
            succeeded=True, summary=summary, candidates=candidates, is_ambiguous=ambiguous
        ),
        asked=asked,
        reference=invoice.invoice_id,
        lines=list(candidates),
    )


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
                f"{line.description} is {money(line.shipbob_amount or Decimal(0))} on "
                f"ShipBob's records and {money(line.receipt_amount or Decimal(0))} on the "
                "receipt."
            )
    return tuple(named)


def _as_claimed_product(item: DamagedItem) -> ClaimedProduct:
    """Turn what the model says was damaged into what the arithmetic reads."""
    return ClaimedProduct(name=item.product_name, quantity=item.quantity, sku=item.sku)
