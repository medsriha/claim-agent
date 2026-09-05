"""Reviewing the amount an investigation recommends, and holding it to the cap.

The investigation decides what to pay. It judges the damage against the photographs and
against how comparable claims were actually settled, and proposes a figure — because how
badly a thing is broken is a judgement, and a rule that always paid a fixed share of the
price could not tell a scuffed box from a smashed bottle.

**This file is the limit on that judgement, not the source of it.** It takes the figure
the investigation proposed and holds it to the reimbursement cap, which is the one
monetary limit ShipBob actually stated (FR-1.20). Over the cap, the recommendation becomes
the cap and says so.

So the guarantee here is narrower than it once was, and it is worth being exact about what
survives:

- **No claim is ever recommended for more than the cap.** That is arithmetic, and no
  investigation can talk its way past it.
- **A figure is money from the first moment it is read.** It arrives as text and is parsed
  into an exact decimal, so it never passes through a floating point number where cents
  could drift.
- **Every result carries its working**: what the investigation proposed, what the items
  cost on the invoice, whether the cap changed the answer, and what is recommended. A bare
  figure is not reviewable; "$40.00 — the investigation proposed $40.00 against items worth
  $52.00, under the cap" is (FR-2.4, NFR-3).

What no longer survives is repeatability. The figure is a judgement, so the same claim can
come back with a different one, and the number in front of a representative is an estimate
to weigh rather than arithmetic to check. That is a deliberate trade — see DESIGN.md.

Nothing here reaches out to anything and nothing here reads a clock.
"""

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
"""What a figure written as money is allowed to look like.

Digits, optionally a decimal point and one or two more. Deliberately narrow: a symbol, a
thousands separator, a minus sign or a third decimal place are all things somebody would
have to interpret, and a payout nobody can read exactly is worse than none.
"""
"""No money at all, written to the cent so every figure in a result reads alike."""


class AmountComponent(BaseModel):
    """One damaged item, and what it cost on the invoice.

    This is context for the figure rather than the figure itself: the investigation
    decides what to pay, and a representative reading its recommendation wants to know
    what the thing was worth in the first place (FR-2.4).

    `unit_price` is the price on the document the items were read from, not the price on
    the order — the two are the same in ShipBob's sample data and are not the same thing.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    product_name: str
    quantity: int
    unit_price: Decimal
    sku: str | None = None

    @property
    def line_total(self) -> Decimal:
        """What this item was worth altogether: the price of one, times how many broke.

        What it *cost*. What is being paid for it is the investigation's judgement and is
        not a share of this — a scuffed box and a smashed bottle can cost the same and be
        worth very different amounts to put right.
        """
        return self.unit_price * self.quantity


class AmountDerivation(BaseModel):
    """A recommended amount together with everything needed to weigh it (FR-2.4).

    Read the three figures together, because the story is in the gaps between them.
    `proposed_usd` is what the investigation judged the damage to be worth.
    `items_total_usd` is what those items cost on the invoice, which is context and not a
    limit — a badly broken thing can be worth less to put right than it cost, and a claim
    can reasonably come to less than the goods did. `amount_usd` is what is actually
    recommended, which is the proposal unless the cap brought it down.

    `cap_applied` says whether it did, and is the thing a representative most needs stated
    rather than inferred: it is the difference between "the investigation judged this to be
    worth a hundred dollars" and "the investigation judged this to be worth more than we
    are allowed to pay".

    `reasoning` is the investigation's own account of why that figure. It is the whole
    justification for the number now, so it is not optional in spirit even where it is
    empty in type — an amount nobody explained is an amount nobody can review (NFR-3).

    `priced_from` names the document the item prices were read from. `components` are the
    damaged items themselves, and an empty tuple means nothing could be tied to the
    invoice at all — which is never a reason to pay.
    """

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
        """True when there is actually something to pay.

        An amount of zero is not payable however it arose — nothing established as
        damaged, or an investigation that judged the damage to be worth nothing.
        Recommending a payment of nothing would put an empty email in front of a
        merchant.
        """
        return self.amount_usd > 0


def review_recommended_amount(
    proposed: str,
    *,
    reasoning: str,
    damaged: Sequence[ClaimedProduct],
    invoice: Invoice | None,
    policy: Policy,
) -> AmountDerivation:
    """Hold the amount an investigation recommends to the cap, and show the working.

    The investigation decides what the damage is worth, weighing the photographs against
    how comparable claims were actually settled. This does two things to that figure and
    nothing else: it reads it as exact money, and it refuses to let it exceed the
    reimbursement cap (FR-1.20). The cap is the one monetary limit ShipBob stated, and it
    is the only thing standing between an investigation's judgement and a payout.

    **The figure arrives as text and is parsed here.** That is deliberate: a number read
    out of a reply would pass through a floating point number on the way, where `0.10`
    cannot be held exactly and cents drift. Text into an exact decimal keeps the figure as
    it was written.

    The items are still read off the invoice, but only as context — what the goods cost is
    worth putting in front of a representative beside what is being recommended for them.
    It is deliberately **not** a limit: a claim may reasonably come to less than the goods
    cost, and nothing in the requirements says it may never come to more, so nothing here
    decides that. Whether it should is a question for whoever owns the requirements, and
    it is written down in DESIGN.md rather than answered here.

    Args:
        proposed: What the investigation recommends paying, written as money — digits with
            at most two decimal places, no currency symbol. Anything else is refused
            rather than interpreted.
        reasoning: The investigation's own account of why that figure. Carried through to
            the result, because it is the whole justification for the number (NFR-3).
        damaged: The products established as damaged, with how many of each. Read for
            context only; an empty sequence prices no items but does not by itself change
            the recommendation.
        invoice: ShipBob's priced record of what the shipment contained. `None` when it
            could not be generated or read, in which case no item context is available.
        policy: Read for the reimbursement cap, so the limit is a configured value rather
            than a number buried in this function (FR-0.7, NFR-7).

    Returns:
        What was proposed, what the items cost, what is recommended, and whether the cap
        changed the answer (FR-2.4).

    Raises:
        ValueError: `proposed` is not money — not a number, or carrying more than two
            decimal places. Refused rather than rounded or reinterpreted: a figure we had
            to guess at is a figure nobody can review, and the caller turns this into an
            representative clarification request instead (NFR-4).
    """
    cap = _to_cents(policy.reimbursement_cap_usd)
    # Named even when nothing could be read from it, so a rep asking "against what?" can
    # see which document was read as well as what it yielded.
    priced_from = invoice.invoice_id if invoice is not None else None

    wanted = _as_money(proposed)
    components = _price_every_item(damaged, invoice) or ()
    items_total = _to_cents(
        sum((component.line_total for component in components), start=Decimal("0"))
    )

    # A proposal landing exactly on the cap is paid in full: the cap has changed nothing,
    # and saying it applied would tell a rep the figure had been trimmed when it had not.
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
    """Read a figure written as text into exact money, or refuse it.

    Accepts digits with at most two decimal places and nothing else — no currency symbol,
    no thousands separator, no exponent, nothing negative. Every one of those is a figure
    somebody would have to interpret, and interpreting a payout is exactly what must not
    happen quietly.

    Raises:
        ValueError: it is not money.
    """
    if _MONEY.fullmatch(written.strip()) is None:
        raise ValueError(
            f"A recommended amount has to be written as money, such as 31.20; got {written!r}."
        )
    return _to_cents(Decimal(written.strip()))


def _price_every_item(
    damaged: Sequence[ClaimedProduct], invoice: Invoice | None
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
        components.append(_component_for(item, invoice.line_items[position]))
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


def _component_for(item: ClaimedProduct, line: OrderLineItem) -> AmountComponent:
    """Price one damaged item against the invoice line it was matched to.

    The name, code and price all come from the invoice rather than from the claim. The
    invoice is the document of record, and ShipBob's payment endpoint identifies a
    product by the name the record uses (FR-1.18, FR-3.3).

    The quantity is held between nothing and the quantity invoiced. Claiming for more
    than was invoiced cannot be right, and paying for more would be the expensive
    mistake; a quantity below nothing would subtract from the other items' totals, which
    would be worse still.

    Nothing here works out what to pay for the item. What it cost is a fact from the
    invoice; what the damage is worth is the investigation's judgement, and the two are
    deliberately kept apart so a representative can see both.
    """
    return AmountComponent(
        product_name=line.name,
        quantity=max(0, min(item.quantity, line.quantity)),
        unit_price=line.unit_price,
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
