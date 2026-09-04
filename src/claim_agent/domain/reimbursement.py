"""How much to recommend paying, and the working that shows how it was reached.

This file exists because of one rule that the rest of the system is arranged
around: **the agent identifies what was damaged, and code works out how much**
(FR-1.21). No monetary figure is ever produced by a model, or read out of
something a model wrote. That is what makes the same claim yield the same figure
every time, and it means the number in front of a rep is arithmetic they can
check rather than an estimate they have to trust.

Three rules decide the figure:

- it is priced from the invoice — the price at the time the order was fulfilled
  (FR-1.18);
- it covers only the damaged items, not the whole order, so a crushed bottle in a
  six-item order reimburses one bottle (FR-1.19);
- it is capped (FR-1.20). The cap is the one policy value ShipBob actually stated.

A bare figure is not reviewable, so nothing here returns one. Every result carries
its own working: which items, at which prices, from which document, and whether
the cap changed the answer. "$52.00" alone tells a rep nothing; "$52.00 — one
Liposomal Tripeptide Collagen at the invoice price, under the cap" can be checked
(FR-2.4, NFR-3).

Money is held as an exact decimal throughout and never as a floating point number,
so cents cannot drift.

Nothing here reaches out to anything and nothing here reads a clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.models import Invoice, OrderLineItem
from claim_agent.policy import Policy

CENTS = Decimal("0.01")
"""How precise money is: two decimal places, because that is what a cent is."""

NOTHING = Decimal("0.00")
"""No money at all, written to the cent so every figure in a result reads alike."""


class AmountComponent(BaseModel):
    """One damaged item's contribution to a recommended amount.

    Held separately rather than summed away so that a rep can see the arithmetic
    line by line and disagree with one item without recomputing the rest (FR-2.4).

    `unit_price` is the price on the document the amount was priced from, not the
    price on the order — the two are the same in ShipBob's sample data and are not
    the same thing.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    product_name: str
    quantity: int
    unit_price: Decimal
    refunded_usd: Decimal
    sku: str | None = None

    @property
    def line_total(self) -> Decimal:
        """What this item was worth altogether: the price of one, times how many broke.

        What it *cost*, not what is being refunded for it — the two differ by the refund
        percentage. Both are kept so a rep can see the step between them (FR-2.4).
        """
        return self.unit_price * self.quantity


class AmountDerivation(BaseModel):
    """A recommended amount together with everything needed to check it (FR-2.4).

    `components` are the damaged items that were priced. `subtotal_usd` is what
    they come to before the cap, and `amount_usd` is what is actually recommended;
    the two differ exactly when `cap_applied` is true, which is the case a rep most
    needs to see stated rather than inferred.

    `priced_from` names the document the prices were taken from — an invoice id —
    so the report can say where the figure came from. It is `None` only when there
    is nothing to price, which is also the one case where an amount of zero is a
    real answer rather than a suspicious one.

    An empty `components` gives an `amount_usd` of zero. That means "nothing was
    established as damaged", which is never a reason to pay and never a reason to
    recommend approval.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    components: tuple[AmountComponent, ...]
    items_total_usd: Decimal
    refund_percentage: int
    subtotal_usd: Decimal
    amount_usd: Decimal
    cap_usd: Decimal
    cap_applied: bool
    priced_from: str | None = None

    @property
    def is_payable(self) -> bool:
        """True when there is actually something to pay.

        An amount of zero is not payable however it arose — nothing damaged, or
        every damaged item priced at nothing. Recommending a payment of nothing
        would put an empty email in front of a merchant.
        """
        return self.amount_usd > 0


def compute_reimbursement(
    damaged: Sequence[ClaimedProduct],
    *,
    invoice: Invoice | None,
    policy: Policy,
) -> AmountDerivation:
    """Work out how much to recommend paying for the damaged items, and show the working.

    This is the deterministic half of the split the whole system is built around: an
    investigation says *what* was damaged, and this says *how much* (FR-1.21). It reads
    only its arguments — no clock, no network, no model — so the same damaged items
    priced against the same invoice always come to the same figure (NFR-1).

    How a figure is reached:

    1. Each damaged item is looked up on the invoice. Its product code is tried first,
       because a code is exact, and its name second, ignoring capitals and extra spaces
       (FR-1.18).
    2. Only the items found are priced, at the invoice's own prices, and only for the
       quantity claimed — never for the whole order (FR-1.19).
    3. The items are added up, and the total is limited to the cap in the claim policy
       (FR-1.20).

    **Anything that cannot be priced prices nothing at all.** If there is no invoice, if
    an item is not on it, if an item could be either of two invoice lines, or if two
    damaged items point at the same invoice line, the result carries no items and comes
    to nothing. It never falls back to the price on the order and never picks between
    two candidates: both would invent a payout (FR-1.13, FR-1.18). Partial pricing is
    ruled out too, because a result showing $52.00 of priced items and an amount of
    $0.00 would read as a mistake rather than as a refusal to guess.

    A result that comes to nothing is not payable, and the caller must not recommend
    paying it. Why it came to nothing can be read off the result: no invoice at all
    leaves `priced_from` empty, an item that could not be found leaves `components`
    empty, and an item the invoice genuinely prices at nothing leaves a component with
    a price of nothing. That last case is real — one sample order carries a free
    promotional insert card — and nothing in the requirements says what a free item
    does to a claim, so it is left visible rather than decided here.

    A quantity higher than the invoice shows is reduced to the invoiced quantity, and a
    quantity below nothing is reduced to nothing. Both only ever lower the figure. The
    reduction is not announced anywhere in the result, because the shape has no field
    for it; a caller that needs to know compares the quantity on the component with the
    quantity that was claimed.

    Args:
        damaged: The products the investigation established as damaged, with how many of
            each. An empty sequence means nothing was established as damaged, which
            prices nothing.
        invoice: ShipBob's priced record of what the shipment contained. `None` when it
            could not be generated or read, which prices nothing rather than falling
            back to the order.
        policy: Read for the reimbursement cap, so the limit is a configured value
            rather than a number buried in this function (FR-0.7, NFR-7).

    Returns:
        The recommended amount together with everything needed to check it: the items
        priced, the total before the cap, the total after it, the cap itself, and
        whether the cap changed the answer (FR-2.4).
    """
    cap = _to_cents(policy.reimbursement_cap_usd)
    # Named even when nothing could be priced from it, so a rep asking "why nothing?"
    # can see which document was read as well as that the answer was nothing.
    priced_from = invoice.invoice_id if invoice is not None else None

    percentage = policy.uninsured_refund_percentage
    components = _price_every_item(damaged, invoice, percentage)
    if components is None:
        return AmountDerivation(
            components=(),
            items_total_usd=NOTHING,
            refund_percentage=percentage,
            subtotal_usd=NOTHING,
            amount_usd=NOTHING,
            cap_usd=cap,
            cap_applied=False,
            priced_from=priced_from,
        )

    items_total = _to_cents(
        sum((component.line_total for component in components), start=Decimal("0"))
    )
    # Each item's share is rounded to cents before they are added up, so the lines a rep
    # reads add up to the total beside them. Rounding the total instead would leave the
    # working looking like it did not.
    subtotal = _to_cents(
        sum((component.refunded_usd for component in components), start=Decimal("0"))
    )
    # A subtotal landing exactly on the cap is paid in full: the cap has changed nothing,
    # and saying it applied would tell a rep the figure had been trimmed when it had not.
    cap_applied = subtotal > cap
    return AmountDerivation(
        components=components,
        items_total_usd=items_total,
        refund_percentage=percentage,
        subtotal_usd=subtotal,
        amount_usd=cap if cap_applied else subtotal,
        cap_usd=cap,
        cap_applied=cap_applied,
        priced_from=priced_from,
    )


def _price_every_item(
    damaged: Sequence[ClaimedProduct], invoice: Invoice | None, percentage: int
) -> tuple[AmountComponent, ...] | None:
    """Price all the damaged items, or refuse to price any of them.

    Returns one priced component per damaged item, in the order they were given. An
    empty tuple means there was nothing to price, which is a real answer.

    Returns `None` — meaning "price nothing" — when any single item cannot be priced
    with confidence: there is no invoice, the item is not on it, it could be either of
    two invoice lines, or two damaged items point at the same invoice line. The last of
    those would otherwise pay twice for one invoiced product, and nobody can say from
    the data whether that is a double claim or two units of it.
    """
    if invoice is None:
        return None

    components: list[AmountComponent] = []
    already_claimed: set[int] = set()
    for item in damaged:
        position = _position_on_invoice(item, invoice.line_items)
        if position is None or position in already_claimed:
            return None
        already_claimed.add(position)
        components.append(_component_for(item, invoice.line_items[position], percentage))
    return tuple(components)


def _position_on_invoice(item: ClaimedProduct, lines: Sequence[OrderLineItem]) -> int | None:
    """Find which invoice line a damaged item is, or say that it cannot be told.

    The product code is tried first and trusted on its own when it matches, because a
    code is exact. Only when no code matches does the name decide, and then only an
    exact name once capitals and extra spaces are ignored.

    Returns `None` when nothing matches and when more than one line matches. Narrowing
    two candidates to one is the judgement this system is not allowed to make: two
    similar products can carry different prices, and choosing would invent the payout
    (FR-1.13).
    """
    by_code = [
        position
        for position, line in enumerate(lines)
        if item.sku is not None and line.sku is not None and _same_text(line.sku, item.sku)
    ]
    matches = by_code or [
        position for position, line in enumerate(lines) if _same_text(line.name, item.name)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _component_for(item: ClaimedProduct, line: OrderLineItem, percentage: int) -> AmountComponent:
    """Price one damaged item against the invoice line it was matched to.

    The name, code and price all come from the invoice rather than from the claim. The
    invoice is the document of record, and ShipBob's payment endpoint identifies a
    product by the name the record uses (FR-1.18, FR-3.3).

    The quantity is held between nothing and the quantity invoiced. Claiming for more
    than was invoiced cannot be right, and paying for more would be the expensive
    mistake; a quantity below nothing would subtract from the other items' totals, which
    would be worse still.

    What is refunded is a percentage of what the item cost, not the whole of it: ShipBob
    reimburses part of the price on an uninsured shipment, and the share is a policy
    value (FR-1.19). It is worked out in exact decimals and rounded to cents half up, the
    way money is normally rounded, so the same item always comes to the same figure.
    """
    quantity = max(0, min(item.quantity, line.quantity))
    cost = line.unit_price * quantity
    return AmountComponent(
        product_name=line.name,
        quantity=quantity,
        unit_price=line.unit_price,
        refunded_usd=_to_cents(cost * Decimal(percentage) / Decimal(100)),
        sku=line.sku,
    )


def _same_text(left: str, right: str) -> bool:
    """Say whether two names or codes should count as the same thing.

    Capitals and surrounding spaces are typing rather than meaning, so they are ignored;
    nothing else is. No word is dropped, no abbreviation expanded, and nothing matches on
    merely starting with the same letters, because a looser rule would quietly pay out on
    the wrong product.

    This is the same rule claim-line matching uses, written out again rather than shared.
    The two are the same by coincidence of the data — the invoice and the order carry
    identical lines — and tying them together would mean a change made for one silently
    changed the other.
    """
    return _for_comparison(left) == _for_comparison(right)


def _for_comparison(value: str) -> str:
    """Reduce a name or code to the form two of them are compared in.

    `casefold` rather than `lower` because it does not depend on the language the machine
    is set to, so the same claim prices the same anywhere (NFR-1).
    """
    return " ".join(value.split()).casefold()


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up.

    The same rounding an order's total uses, so two figures a rep compares were reached
    the same way. Half up is how money is normally rounded; the alternative Python
    reaches for by default rounds half to even, which would make some claims a cent
    cheaper for no reason anyone could explain.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)
