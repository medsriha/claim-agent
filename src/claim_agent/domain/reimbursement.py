from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.models import Invoice, OrderLineItem
from claim_agent.policy import Policy

CENTS = Decimal("0.01")
"""How precise money is: two decimal places, because that is what a cent is."""

NOTHING = Decimal("0.00")

_MONEY = re.compile(r"\d+(?:\.\d{1,2})?")
"""What a figure written as money is allowed to look like."""
"""No money at all, written to the cent so every figure in a result reads alike."""


class AmountComponent(BaseModel):
    """One damaged item, and what it cost on the invoice."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    product_name: str
    quantity: int
    unit_price: Decimal
    sku: str | None = None

    @property
    def line_total(self) -> Decimal:
        """What this item was worth altogether: the price of one, times how many broke."""
        return self.unit_price * self.quantity


class AmountDerivation(BaseModel):
    """A recommended amount together with everything needed to weigh it (FR-2.4)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    components: tuple[AmountComponent, ...]
    items_total_usd: Decimal
    proposed_usd: Decimal
    amount_usd: Decimal
    cap_usd: Decimal
    cap_applied: bool
    reasoning: str = ""
    priced_from: str | None = None

    @property
    def is_payable(self) -> bool:
        """True when there is actually something to pay."""
        return self.amount_usd > 0


def review_recommended_amount(
    proposed: str,
    *,
    reasoning: str,
    damaged: Sequence[ClaimedProduct],
    invoice: Invoice | None,
    policy: Policy,
) -> AmountDerivation:
    """Hold the amount an investigation recommends to the cap, and show the working."""
    cap = _to_cents(policy.reimbursement_cap_usd)

    priced_from = invoice.invoice_id if invoice is not None else None

    wanted = _as_money(proposed)
    components = _price_every_item(damaged, invoice) or ()
    items_total = _to_cents(
        sum((component.line_total for component in components), start=Decimal("0"))
    )

    cap_applied = wanted > cap
    return AmountDerivation(
        components=components,
        items_total_usd=items_total,
        proposed_usd=wanted,
        amount_usd=cap if cap_applied else wanted,
        cap_usd=cap,
        cap_applied=cap_applied,
        reasoning=reasoning,
        priced_from=priced_from,
    )


def _as_money(written: str) -> Decimal:
    """Read a figure written as text into exact money, or refuse it."""
    if _MONEY.fullmatch(written.strip()) is None:
        raise ValueError(
            f"A recommended amount has to be written as money, such as 31.20; got {written!r}."
        )
    return _to_cents(Decimal(written.strip()))


def _price_every_item(
    damaged: Sequence[ClaimedProduct], invoice: Invoice | None
) -> tuple[AmountComponent, ...] | None:
    """Price all the damaged items, or refuse to price any of them."""
    if invoice is None:
        return None

    components: list[AmountComponent] = []
    already_claimed: set[int] = set()
    for item in damaged:
        position = _position_on_invoice(item, invoice.line_items)
        if position is None or position in already_claimed:
            return None
        already_claimed.add(position)
        components.append(_component_for(item, invoice.line_items[position]))
    return tuple(components)


def _position_on_invoice(item: ClaimedProduct, lines: Sequence[OrderLineItem]) -> int | None:
    """Find which invoice line a damaged item is, or say that it cannot be told."""
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


def _component_for(item: ClaimedProduct, line: OrderLineItem) -> AmountComponent:
    """Price one damaged item against the invoice line it was matched to."""
    return AmountComponent(
        product_name=line.name,
        quantity=max(0, min(item.quantity, line.quantity)),
        unit_price=line.unit_price,
        sku=line.sku,
    )


def _same_text(left: str, right: str) -> bool:
    """Say whether two names or codes should count as the same thing."""
    return _for_comparison(left) == _for_comparison(right)


def _for_comparison(value: str) -> str:
    """Reduce a name or code to the form two of them are compared in."""
    return " ".join(value.split()).casefold()


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def nothing_priced_yet() -> AmountDerivation:
    """A figure of nothing, for a product no investigation has reached yet."""
    return AmountDerivation(
        components=(),
        items_total_usd=Decimal("0.00"),
        proposed_usd=Decimal("0.00"),
        amount_usd=Decimal("0.00"),
        cap_usd=Decimal("0.00"),
        cap_applied=False,
        reasoning="",
        priced_from=None,
    )
