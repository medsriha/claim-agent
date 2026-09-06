from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Order, OrderLineItem


class MatchOutcome(StrEnum):
    """How a claimed product relates to the products on the order (FR-1a.2)."""

    MATCHED = "matched"
    NOT_ON_ORDER = "not_on_order"
    AMBIGUOUS = "ambiguous"


class ClaimedProduct(BaseModel):
    """A product an investigation says was damaged, before it is tied to the order."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    quantity: int
    sku: str | None = None


class ClaimLine(BaseModel):
    """One claimed product within a case — the unit of investigation and payment."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    claim_line_id: str
    claimed: ClaimedProduct
    match: MatchOutcome
    order_line: OrderLineItem | None = None
    candidate_order_lines: tuple[OrderLineItem, ...] = ()
    damage_attachment_ids: tuple[str, ...] = ()

    @property
    def is_matched(self) -> bool:
        """True when exactly one product on the order is this claim line's product."""
        return self.match is MatchOutcome.MATCHED

    @property
    def product_name(self) -> str:
        """The product's name, taken from the order whenever the line matched one."""
        return self.order_line.name if self.order_line is not None else self.claimed.name

    @property
    def sku(self) -> str | None:
        """The product's code, from the order where it matched, otherwise as claimed."""
        if self.order_line is not None:
            return self.order_line.sku
        return self.claimed.sku

    @property
    def unit_price(self) -> Decimal | None:
        """What one of these cost on the order, or `None` if the line matched nothing."""
        return self.order_line.unit_price if self.order_line is not None else None


def build_claim_lines(
    case_id: str,
    claimed: Sequence[ClaimedProduct],
    order: Order | None,
    damage_attachments: Sequence[Sequence[str]] | None = None,
) -> tuple[ClaimLine, ...]:
    """Turn the products an investigation identified into claim lines (FR-1a.2)."""
    if damage_attachments is not None and len(damage_attachments) != len(claimed):
        raise ValueError(
            "damage_attachments must carry one entry per claimed product; "
            f"got {len(damage_attachments)} for {len(claimed)} products."
        )

    attachments_by_product = (
        [tuple(group) for group in damage_attachments]
        if damage_attachments is not None
        else [() for _ in claimed]
    )
    order_lines = order.line_items if order is not None else ()

    in_order = sorted(
        zip(claimed, attachments_by_product, strict=True),
        key=lambda pair: (pair[0].sku or "", pair[0].name),
    )

    lines: list[ClaimLine] = []
    for position, (product, attachment_ids) in enumerate(in_order, start=1):
        candidates = _candidates_for(product, order_lines)
        lines.append(
            ClaimLine(
                claim_line_id=f"{case_id}-L{position:02d}",
                claimed=product,
                match=_outcome_for(candidates),
                order_line=candidates[0] if len(candidates) == 1 else None,
                candidate_order_lines=candidates if len(candidates) > 1 else (),
                damage_attachment_ids=attachment_ids,
            )
        )
    return tuple(lines)


def _candidates_for(
    product: ClaimedProduct, order_lines: Sequence[OrderLineItem]
) -> tuple[OrderLineItem, ...]:
    """Find every order line that could be this claimed product."""
    by_sku = tuple(
        line
        for line in order_lines
        if product.sku is not None
        and line.sku is not None
        and _normalised(line.sku) == _normalised(product.sku)
    )
    if by_sku:
        return by_sku
    return tuple(
        line for line in order_lines if _normalised(line.name) == _normalised(product.name)
    )


def _outcome_for(candidates: Sequence[OrderLineItem]) -> MatchOutcome:
    """Say what a number of candidate order lines means for a claim line."""
    if not candidates:
        return MatchOutcome.NOT_ON_ORDER
    if len(candidates) > 1:
        return MatchOutcome.AMBIGUOUS
    return MatchOutcome.MATCHED


def _normalised(value: str) -> str:
    """Reduce a name or code to what should count as the same thing."""
    return " ".join(value.split()).casefold()
