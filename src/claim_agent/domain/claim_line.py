from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Order, OrderLineItem


class MatchOutcome(StrEnum):
    """How a claimed product relates to the products on the order (FR-1a.2).

    `MATCHED` means exactly one order line is this product, so its name, code and
    price are known and a reimbursement can be priced.

    `NOT_ON_ORDER` means no order line is this product. The claim line still
    exists and is still investigated and reported on — a merchant claiming for
    something they did not order is a finding a rep needs to see, not a record to
    quietly drop.

    `AMBIGUOUS` means more than one order line could be this product. This is the
    outcome that must never be resolved by picking one: the two candidates can
    carry different prices, so choosing would invent the payout (FR-1.13).
    """

    MATCHED = "matched"
    NOT_ON_ORDER = "not_on_order"
    AMBIGUOUS = "ambiguous"


class ClaimedProduct(BaseModel):
    """A product an investigation says was damaged, before it is tied to the order.

    This is the raw claim, in whatever words the evidence gave: the name as it was
    read off a photograph or a description, the product code if one was legible,
    and how many of them the merchant is claiming for.

    It is deliberately separate from `ClaimLine`. What was claimed and what the
    order actually holds are two different facts, and matching the first to the
    second is a step that can fail in ways a rep needs to know about.

    `sku` is `None` when no product code could be established, which is common: a
    photograph of a broken bottle rarely shows one.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    quantity: int
    sku: str | None = None


class ClaimLine(BaseModel):
    """One claimed product within a case — the unit of investigation and payment.

    A claim covering two damaged products is two of these, each investigated on
    its own, reported on its own, approved on its own and paid on its own
    (FR-1b.1). A claim covering one damaged product is one of these, through
    exactly the same machinery — there is no shortcut for the simple case
    (FR-1a.5).

    `claim_line_id` is worked out from the case and the line's position in a fixed
    ordering, so the same claim always produces the same identifiers.

    `order_line` is the product on the order this line is for, and is `None`
    whenever `match` is not `MATCHED` — either because no order line is this
    product or because several could be. Read the price and the exact product name
    through the properties below rather than off `order_line`, so that an unmatched
    line cannot be mistaken for a free one.

    `damage_attachment_ids` are the images the investigation thought showed damage
    to *this* product. They are a starting point for the per-line run, not its
    conclusion: the run may look elsewhere, and may disagree.
    """

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
        """The product's name, taken from the order whenever the line matched one.

        ShipBob's payment endpoint identifies a product by its name as free text
        rather than by any code, so a payout has to carry the name exactly as the
        order writes it (FR-3.3). Where nothing matched, the merchant's own words
        are all there is, and no payment can be made from them anyway.
        """
        return self.order_line.name if self.order_line is not None else self.claimed.name

    @property
    def sku(self) -> str | None:
        """The product's code, from the order where it matched, otherwise as claimed."""
        if self.order_line is not None:
            return self.order_line.sku
        return self.claimed.sku

    @property
    def unit_price(self) -> Decimal | None:
        """What one of these cost on the order, or `None` if the line matched nothing.

        `None` means the price is not known, which is a different thing from a
        product that was free. Nothing may be priced from an unmatched line.
        """
        return self.order_line.unit_price if self.order_line is not None else None


def build_claim_lines(
    case_id: str,
    claimed: Sequence[ClaimedProduct],
    order: Order | None,
    damage_attachments: Sequence[Sequence[str]] | None = None,
) -> tuple[ClaimLine, ...]:
    """Turn the products an investigation identified into claim lines (FR-1a.2).

    Each claimed product is matched against the order's line items, and the result
    is one claim line per claimed product — including for products the order does
    not hold, because that is a finding rather than a reason to drop the line.

    Matching tries the product code first, because a code is exact, and falls back
    to the product's name with capitals and surrounding spaces ignored. Anything
    matching more than one order line is reported as ambiguous and never resolved
    by choosing (FR-1.13).

    The lines come back in a fixed order — by product code, then by name — and
    their identifiers follow that order, so the same claim always produces the same
    lines with the same names for them however the products were listed going in
    (NFR-1).

    Args:
        case_id: The support case these lines belong to, for example `CASE-1001`.
        claimed: The products the investigation says were damaged. May be empty,
            which produces no lines at all; the caller decides what that means.
        order: The order the goods came from. `None` when it could not be read, in
            which case every line is `NOT_ON_ORDER` — nothing can be priced, and
            that shows up honestly rather than as a match against nothing.
        damage_attachments: For each claimed product, in the same order, the
            images thought to show damage to it. Omit it entirely when no images
            have been tied to products yet.

    Returns:
        One claim line per claimed product, in the fixed order described above.

    Raises:
        ValueError: `damage_attachments` was given but does not have exactly one
            entry per claimed product. That mismatch would silently attach one
            product's photographs to another, so it stops here.
    """
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

    # Sorted before the identifiers are handed out, so the identifiers describe a
    # fixed ordering rather than the order the products happened to arrive in.
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
    """Find every order line that could be this claimed product.

    The product code is tried first and, when it matches anything, is trusted on
    its own: a code is exact, and a merchant whose code matches one line but whose
    wording matches another is still claiming for the line they named by code.
    Only when no code matches does the name decide.

    Returns every candidate rather than a best one. Narrowing two candidates to
    one is precisely the judgement this system is not allowed to make (FR-1.13).
    """
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
    """Reduce a name or code to what should count as the same thing.

    Capitals and surrounding spaces are typing rather than meaning. Nothing more
    is done than that: no word is dropped, no abbreviation expanded, and nothing
    is matched on merely starting with the same letters. A looser rule here would
    quietly pay out on the wrong product.
    """
    return " ".join(value.split()).casefold()
