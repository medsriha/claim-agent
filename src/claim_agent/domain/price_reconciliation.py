"""Comparing ShipBob's prices against the prices on the customer's own receipt.

A merchant claiming for a damaged parcel usually sends a picture of a document their own
customer was given: an order confirmation, a sales order, a till receipt. That document
carries prices. ShipBob's own records carry prices too. **In every sample claim that has
any evidence at all, the two disagree.**

That matters because a reimbursement is worked out against a price. One sample claim is
priced at $195.94 in ShipBob's records, while the receipt shows the customer paid $134.99
after a discount. Settling against the first figure overpays by sixty dollars, and nothing
notices, because until now nothing had ever put the two documents side by side. This file
is that comparison.

**It does not decide which price is the right one.** Nobody has said whether ShipBob's
catalogue price or the price the customer actually paid is what a claim should be settled
against, and answering that here would be inventing money. So both figures are reported,
the gap between them is reported, and the written summary says in plain words that a
person chooses. (No requirement covers this; see DESIGN.md. The nearest are FR-1.13, which
forbids narrowing two candidates down to one, and FR-1.20 and FR-1.21, which govern the
recommended amount and the cap on it.)

Three more things it deliberately does not do:

- **It does not read documents.** Both sides arrive already read: ShipBob's lines come
  from the order or the invoice, and the receipt's lines come from whatever read the
  picture. Reading is somebody else's job, and doing it here would make this impossible to
  test without a model.
- **It does not convert money.** A currency label can be passed in and is carried out
  again, so a reader can see that one side is in pounds and the other in dollars. Nothing
  is multiplied by a rate. Two sides in different money is a fact worth showing, not one
  worth papering over.
- **It never chooses between two candidate lines.** Where a product code or a name could
  describe more than one line on the other document, every candidate is reported and none
  is picked (FR-1.13).

Nothing here reaches out to anything and nothing here reads a clock. The same two
documents always produce the same comparison, with the same entries in the same order
(NFR-1). Money is exact throughout: every figure is a decimal, and none of them ever
passes through a floating point number where cents could drift.
"""

from __future__ import annotations

from collections.abc import Container, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, computed_field

from claim_agent.domain.models import OrderLineItem
from claim_agent.policy import Policy

_CENTS = Decimal("0.01")
"""How precise money is: two decimal places, because that is what a cent is."""

_FRACTION_PLACES = Decimal("0.0001")
"""How precise a "how far apart are these two prices" figure is.

Four decimal places, so that a gap of a hundredth of a percent is still visible. The
rounded figure is also the figure that is compared against the threshold, so what a reader
sees is exactly what decided whether the gap was worth flagging.
"""

_NOTHING = Decimal("0.00")
"""No money at all, written to the cent so every figure in a result reads alike."""


class LineMatchKind(StrEnum):
    """How one line on a document relates to the lines on the other document.

    `MATCHED_ON_SKU` means exactly one line on each document carries the same product
    code, so the two prices are certainly for the same product and can be compared.

    `MATCHED_ON_NAME` means no product code tied them together but exactly one line on
    each document has the same product name. Weaker than a code, and it is reported as a
    different thing for that reason.

    `SHIPBOB_ONLY` means the line is in ShipBob's records and nothing on the receipt looks
    like it. `RECEIPT_ONLY` is the mirror image. Neither is an error: a receipt commonly
    carries shipping and tax that ShipBob's records never mention, and a customer may have
    been billed for something that shipped separately.

    `AMBIGUOUS` means the line could be more than one line on the other document — the
    same code or the same name appears twice. No comparison is made in that case and
    neither candidate is chosen, because two similar products can carry different prices
    and picking one would invent the answer (FR-1.13).
    """

    MATCHED_ON_SKU = "matched_on_sku"
    MATCHED_ON_NAME = "matched_on_name"
    SHIPBOB_ONLY = "shipbob_only"
    RECEIPT_ONLY = "receipt_only"
    AMBIGUOUS = "ambiguous"


class ReceiptLine(BaseModel):
    """One line as it is printed on the customer's own receipt.

    This is the evidence side of the comparison, and it arrives already read: whatever
    looked at the picture decided what the words and figures on it were. Nothing here
    re-reads anything.

    `description` is the line as the receipt words it, which may be a product name, but
    may equally be "Shipping", "Tax" or "Discount" — a receipt carries lines that
    ShipBob's records have no idea about.

    `sku` is the product code printed on the line, and is `None` when the receipt shows
    none, which is common. `quantity` is how many of the item that line covers, and is
    `None` when the receipt does not say.

    `amount` is what the line came to — the figure printed against it, for however many of
    the item it covers, not the price of one. A discount line arrives as a negative amount,
    because that is what it does to the bill.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    sku: str | None = None
    quantity: int | None = None
    amount: Decimal


class LineComparison(BaseModel):
    """What was found about one product across the two documents.

    Read `kind` first: it says whether the two documents both mention this thing, only one
    of them does, or it could not be told apart from something else. Only a matched line
    has figures on both sides, and only a matched line can be said to diverge.

    `description` is the name to show. For a matched line it is ShipBob's wording, because
    ShipBob's records are the system a payment is eventually made through; for a line only
    the receipt has, it is the receipt's wording.

    `difference` is how far apart the two figures are, always as a positive amount — the
    direction is visible in the two figures themselves, and an absolute gap is what a
    threshold can be set against. `difference_fraction` is that gap as a share of ShipBob's
    figure, so a five dollar gap on a five dollar item and on a five hundred dollar item do
    not read the same. It is `None` when ShipBob's figure is nothing at all, since nothing
    can be a share of nothing.

    `diverges` is the flag a representative acts on: the gap is bigger than the claim
    policy says is worth mentioning. A line where ShipBob's figure is nothing and the
    receipt charges something diverges too, because any gap from nothing is a complete one.

    `ambiguous_with` is filled only for an ambiguous line, and holds how each of the
    candidate lines on the other document reads, so a reader can see what the confusion is
    rather than being told only that there was one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LineMatchKind
    description: str
    sku: str | None = None
    shipbob_quantity: int | None = None
    shipbob_amount: Decimal | None = None
    receipt_quantity: int | None = None
    receipt_amount: Decimal | None = None
    difference: Decimal | None = None
    difference_fraction: Decimal | None = None
    diverges: bool = False
    ambiguous_with: tuple[str, ...] = ()


class PriceReconciliation(BaseModel):
    """Everything found by holding the two documents up against each other.

    `lines` is the per-product story, in a fixed order: ShipBob's lines as ShipBob lists
    them, then whatever is left on the receipt in the order the receipt lists it. A matched
    pair appears once, in ShipBob's position.

    The document-level figures are the ones that catch a claim priced off the wrong sheet
    of paper. `shipbob_total` is what ShipBob's lines come to. `receipt_lines_total` is
    what the receipt's lines come to. `receipt_total` is the figure the comparison actually
    uses: the total printed on the receipt when one was given, and otherwise the sum of its
    lines. `receipt_total_is_stated` says which of the two it was, and it matters — a
    receipt showing a discount, shipping or tax will print a total that its own lines do
    not add up to, and the printed figure is the one the customer paid.

    `line_counts_differ` is a finding in its own right, and often the most useful one. Two
    documents that do not even list the same number of lines are quite likely describing
    different things, and no comparison of totals is worth much until somebody has looked
    at why.

    `shipbob_currency` and `receipt_currency` are carried through exactly as they were
    given. Nothing here converts between them; `same_currency` says whether they can be
    compared at all, and `None` there means nobody recorded enough to tell.

    `divergence_threshold_fraction` is the setting the flags were decided by, kept beside
    the result so a reader can see what "too far apart" meant on this run (NFR-3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[LineComparison, ...]
    shipbob_total: Decimal
    receipt_lines_total: Decimal
    receipt_total: Decimal
    receipt_total_is_stated: bool
    total_difference: Decimal
    total_difference_fraction: Decimal | None
    totals_diverge: bool
    shipbob_line_count: int
    receipt_line_count: int
    line_counts_differ: bool
    shipbob_currency: str | None = None
    receipt_currency: str | None = None
    divergence_threshold_fraction: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def same_currency(self) -> bool | None:
        """Whether the two sides are known to be in the same money.

        `True` only when both sides said what money they were in and said the same thing.
        `False` when both said, and disagreed. `None` when at least one of them did not
        say, which is the usual case — ShipBob's records carry no currency field anywhere,
        so a claim can easily be compared against a receipt in pounds without either
        document ever mentioning it. `None` means "cannot tell", not "fine".
        """
        if self.shipbob_currency is None or self.receipt_currency is None:
            return None
        return _comparable(self.shipbob_currency) == _comparable(self.receipt_currency)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_findings(self) -> bool:
        """Whether there is anything here about the prices or the lines worth reading.

        True when the totals are far apart, when the two documents list different numbers
        of lines, when any matched line's price diverges, or when any line appears on only
        one of the documents or could not be told apart from another.

        The currency question is deliberately left out of this. It is almost never settled
        by the documents, so folding it in would make every comparison report a finding and
        the flag would stop meaning anything. Read `same_currency` for that.
        """
        if self.totals_diverge or self.line_counts_differ:
            return True
        return any(
            line.diverges
            or line.kind not in (LineMatchKind.MATCHED_ON_SKU, LineMatchKind.MATCHED_ON_NAME)
            for line in self.lines
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        """The whole comparison in a few plain sentences, for a person to read.

        It always ends by saying that which price is right is not settled here. That is the
        one thing a representative must not take from this: the system found a gap, and
        somebody has to decide what to do about it.
        """
        return _summarise(self)


def reconcile_prices(
    shipbob_lines: Sequence[OrderLineItem],
    receipt_lines: Sequence[ReceiptLine],
    *,
    policy: Policy,
    receipt_total: Decimal | None = None,
    shipbob_currency: str | None = None,
    receipt_currency: str | None = None,
) -> PriceReconciliation:
    """Compare what ShipBob says a shipment was worth with what the customer's receipt says.

    Lines are tied together in two passes. First by product code: where exactly one line on
    each document carries the same code, that is a pair, because a code is exact. Then by
    product name, under the same rule, for whatever is left. Capitals and extra spaces are
    ignored in both, because they are typing rather than meaning; nothing looser than that
    is allowed, so a name that merely starts the same is not a match and a product code
    with an extra suffix on the end is a different code.

    Anything a code or a name could describe more than once is reported as ambiguous and
    left that way. Choosing between two candidates is exactly the judgement this system is
    not allowed to make, because they can carry different prices and the choice would
    become the payout (FR-1.13).

    Nothing is ever refused and nothing is ever raised. Two empty documents, a receipt with
    no lines, prices that make no sense together — each of those is an answer that gets
    reported, because a representative can act on a finding and cannot act on an error
    (NFR-4).

    Args:
        shipbob_lines: The priced lines from ShipBob's own record of the shipment, taken
            from the order or from the generated invoice. Empty is allowed and means
            ShipBob priced nothing, which is itself worth reporting.
        receipt_lines: The lines read off the customer's receipt, in the order they are
            printed. Empty is allowed: a total may have been legible when the individual
            lines were not.
        policy: Read for how far apart two prices may sit before it is worth telling a
            representative, so the threshold is a setting rather than a number buried in
            this file (FR-0.7, NFR-7).
        receipt_total: The total printed on the receipt, when one was legible. Give it
            whenever it is known, even if it looks wrong: a receipt with a discount,
            shipping or tax prints a total its own lines do not add up to, and the printed
            figure is what the customer actually paid. Left out, the receipt's lines are
            added up instead.
        shipbob_currency: What money ShipBob's figures are in, if anybody knows. ShipBob's
            API has no currency field, so this is normally `None`.
        receipt_currency: What money the receipt's figures are in, if it was legible.
            Carried through untouched; no conversion is ever done.

    Returns:
        The per-line comparison, the document totals, whether the two documents even list
        the same number of lines, and a plain-words summary — which says, always, that
        which of the two prices is right is for a person to decide.
    """
    pairing = _pair_up(shipbob_lines, receipt_lines)
    threshold = policy.price_divergence_fraction

    entries: list[LineComparison] = []
    for position, shipbob_line in enumerate(shipbob_lines):
        entries.append(_shipbob_entry(shipbob_line, position, receipt_lines, pairing, threshold))
    for position, receipt_line in enumerate(receipt_lines):
        if position in pairing.resolved_receipt and position not in pairing.ambiguous_receipt:
            continue
        entries.append(_receipt_entry(receipt_line, position, pairing))

    shipbob_total = _to_cents(sum((line.line_total for line in shipbob_lines), start=_NOTHING))
    lines_total = _to_cents(sum((line.amount for line in receipt_lines), start=_NOTHING))
    compared_total = _to_cents(receipt_total) if receipt_total is not None else lines_total

    gap = abs(shipbob_total - compared_total)
    gap_fraction = _as_fraction_of(gap, shipbob_total)

    return PriceReconciliation(
        lines=tuple(entries),
        shipbob_total=shipbob_total,
        receipt_lines_total=lines_total,
        receipt_total=compared_total,
        receipt_total_is_stated=receipt_total is not None,
        total_difference=gap,
        total_difference_fraction=gap_fraction,
        totals_diverge=_is_divergent(gap, gap_fraction, threshold),
        shipbob_line_count=len(shipbob_lines),
        receipt_line_count=len(receipt_lines),
        line_counts_differ=len(shipbob_lines) != len(receipt_lines),
        shipbob_currency=shipbob_currency,
        receipt_currency=receipt_currency,
        divergence_threshold_fraction=threshold,
    )


@dataclass
class _Pairing:
    """Which line was tied to which, built up one pass at a time.

    `matched` maps a position in ShipBob's lines to the receipt position it was paired
    with and how they were paired. The two `ambiguous` maps hold, for a line that could be
    more than one line on the other document, how each of those candidates reads. The two
    `resolved` sets are simply everything already accounted for, so a later pass leaves it
    alone.
    """

    matched: dict[int, tuple[int, LineMatchKind]] = field(default_factory=dict)
    ambiguous_shipbob: dict[int, tuple[str, ...]] = field(default_factory=dict)
    ambiguous_receipt: dict[int, tuple[str, ...]] = field(default_factory=dict)
    resolved_shipbob: set[int] = field(default_factory=set)
    resolved_receipt: set[int] = field(default_factory=set)


def _pair_up(
    shipbob_lines: Sequence[OrderLineItem], receipt_lines: Sequence[ReceiptLine]
) -> _Pairing:
    """Work out which line on one document is which line on the other.

    Product codes are tried across both documents first and names second, because a code
    is exact and a name is a description. A line paired by its code is never reconsidered
    by its name.
    """
    shipbob_names = [line.name for line in shipbob_lines]
    receipt_names = [line.description for line in receipt_lines]

    pairing = _Pairing()
    _pair_on(
        pairing,
        kind=LineMatchKind.MATCHED_ON_SKU,
        shipbob_keys=[_comparable(line.sku) for line in shipbob_lines],
        receipt_keys=[_comparable(line.sku) for line in receipt_lines],
        shipbob_names=shipbob_names,
        receipt_names=receipt_names,
    )
    _pair_on(
        pairing,
        kind=LineMatchKind.MATCHED_ON_NAME,
        shipbob_keys=[_comparable(name) for name in shipbob_names],
        receipt_keys=[_comparable(name) for name in receipt_names],
        shipbob_names=shipbob_names,
        receipt_names=receipt_names,
    )
    return pairing


def _pair_on(
    pairing: _Pairing,
    *,
    kind: LineMatchKind,
    shipbob_keys: Sequence[str | None],
    receipt_keys: Sequence[str | None],
    shipbob_names: Sequence[str],
    receipt_names: Sequence[str],
) -> None:
    """Pair up whatever the given keys tie together, and record what they confuse.

    A key is a product code in one pass and a product name in the other. A key held by
    exactly one line on each document is a pair. A key held by two lines on either document
    ties nothing: every line carrying it is marked ambiguous, on both sides, and none of
    them is chosen between (FR-1.13). A key nothing on the other document carries is left
    alone, so the next pass — or, at the end, the report — can deal with it.

    Lines are visited in the order the receipt lists them, and every line a key touches is
    settled at once, so the outcome does not depend on which line happened to be looked at
    first.
    """
    shipbob_by_key = _group_by_key(shipbob_keys, already_settled=pairing.resolved_shipbob)
    receipt_by_key = _group_by_key(receipt_keys, already_settled=pairing.resolved_receipt)

    for receipt_position, key in enumerate(receipt_keys):
        if key is None or receipt_position in pairing.resolved_receipt:
            continue
        shipbob_candidates = shipbob_by_key.get(key, [])
        if not shipbob_candidates:
            continue

        receipt_candidates = receipt_by_key[key]
        if len(shipbob_candidates) == 1 and len(receipt_candidates) == 1:
            shipbob_position = shipbob_candidates[0]
            pairing.matched[shipbob_position] = (receipt_position, kind)
            pairing.resolved_shipbob.add(shipbob_position)
            pairing.resolved_receipt.add(receipt_position)
            continue

        for shipbob_position in shipbob_candidates:
            pairing.ambiguous_shipbob[shipbob_position] = tuple(
                receipt_names[position] for position in receipt_candidates
            )
            pairing.resolved_shipbob.add(shipbob_position)
        for position in receipt_candidates:
            pairing.ambiguous_receipt[position] = tuple(
                shipbob_names[candidate] for candidate in shipbob_candidates
            )
            pairing.resolved_receipt.add(position)


def _group_by_key(
    keys: Sequence[str | None], *, already_settled: Container[int]
) -> dict[str, list[int]]:
    """Collect the positions of every line sharing a key, in the order they appear.

    Lines with no key, and lines an earlier pass already settled, are left out. Positions
    stay in document order so that everything downstream is repeatable (NFR-1).
    """
    groups: dict[str, list[int]] = {}
    for position, key in enumerate(keys):
        if key is None or position in already_settled:
            continue
        groups.setdefault(key, []).append(position)
    return groups


def _shipbob_entry(
    shipbob_line: OrderLineItem,
    position: int,
    receipt_lines: Sequence[ReceiptLine],
    pairing: _Pairing,
    threshold: Decimal,
) -> LineComparison:
    """Write up one of ShipBob's lines: paired, confused with something, or unanswered."""
    pair = pairing.matched.get(position)
    if pair is not None:
        receipt_position, kind = pair
        return _matched_entry(shipbob_line, receipt_lines[receipt_position], kind, threshold)

    candidates = pairing.ambiguous_shipbob.get(position)
    if candidates is not None:
        return LineComparison(
            kind=LineMatchKind.AMBIGUOUS,
            description=shipbob_line.name,
            sku=shipbob_line.sku,
            shipbob_quantity=shipbob_line.quantity,
            shipbob_amount=_to_cents(shipbob_line.line_total),
            ambiguous_with=candidates,
        )

    return LineComparison(
        kind=LineMatchKind.SHIPBOB_ONLY,
        description=shipbob_line.name,
        sku=shipbob_line.sku,
        shipbob_quantity=shipbob_line.quantity,
        shipbob_amount=_to_cents(shipbob_line.line_total),
    )


def _receipt_entry(receipt_line: ReceiptLine, position: int, pairing: _Pairing) -> LineComparison:
    """Write up a receipt line that no single line of ShipBob's could be tied to."""
    candidates = pairing.ambiguous_receipt.get(position)
    kind = LineMatchKind.AMBIGUOUS if candidates is not None else LineMatchKind.RECEIPT_ONLY
    return LineComparison(
        kind=kind,
        description=receipt_line.description,
        sku=receipt_line.sku,
        receipt_quantity=receipt_line.quantity,
        receipt_amount=_to_cents(receipt_line.amount),
        ambiguous_with=candidates if candidates is not None else (),
    )


def _matched_entry(
    shipbob_line: OrderLineItem,
    receipt_line: ReceiptLine,
    kind: LineMatchKind,
    threshold: Decimal,
) -> LineComparison:
    """Compare the two figures for one product that both documents agree exists.

    ShipBob's figure is what its line came to — the price of one times how many — because
    that is the like-for-like comparison against the amount printed on a receipt line. A
    receipt that prints the price of one where ShipBob's line covers three will therefore
    look like a large gap, and that is the honest reading of two documents that do not
    agree on what they are counting.

    The name and the product code shown are ShipBob's wherever it has them, because that is
    the record a payment is eventually made through (FR-3.3).
    """
    shipbob_amount = _to_cents(shipbob_line.line_total)
    receipt_amount = _to_cents(receipt_line.amount)
    gap = abs(shipbob_amount - receipt_amount)
    fraction = _as_fraction_of(gap, shipbob_amount)
    return LineComparison(
        kind=kind,
        description=shipbob_line.name,
        sku=shipbob_line.sku if shipbob_line.sku is not None else receipt_line.sku,
        shipbob_quantity=shipbob_line.quantity,
        shipbob_amount=shipbob_amount,
        receipt_quantity=receipt_line.quantity,
        receipt_amount=receipt_amount,
        difference=gap,
        difference_fraction=fraction,
        diverges=_is_divergent(gap, fraction, threshold),
    )


def _as_fraction_of(gap: Decimal, reference: Decimal) -> Decimal | None:
    """Express a gap as a share of the figure it is a gap from.

    `None` when that figure is nothing at all: nothing can be a share of nothing, and
    returning a very large number instead would read like a measurement when it is not one.

    The size of the reference is used and not its sign, so a figure that somehow arrives
    negative gives a positive share rather than an upside-down one.
    """
    if reference == 0:
        return None
    return (gap / abs(reference)).quantize(_FRACTION_PLACES, rounding=ROUND_HALF_UP)


def _is_divergent(gap: Decimal, fraction: Decimal | None, threshold: Decimal) -> bool:
    """Say whether a gap between two prices is big enough to be worth mentioning.

    A gap exactly on the threshold is not flagged. The setting reads as how far apart two
    prices may sit, so sitting exactly that far apart is still allowed.

    Where the share could not be worked out — ShipBob priced the line at nothing — any gap
    at all counts, because a charge on the receipt against nothing in ShipBob's records is
    a complete disagreement however small the figure is.
    """
    if fraction is None:
        return gap > 0
    return fraction > threshold


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up.

    The same rounding the rest of the system uses, so two figures a representative compares
    were reached the same way. Half up is how money is normally rounded; Python's own
    default rounds half to even, which would make the odd figure a cent different for no
    reason anybody could explain.
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _comparable(value: str | None) -> str | None:
    """Reduce a name, a product code or a currency label to the form two are compared in.

    Capitals and extra spaces are typing rather than meaning, so they are ignored. Nothing
    else is: no word is dropped, no abbreviation expanded, and nothing matches on merely
    starting with the same letters. A looser rule would quietly tie a claim to the wrong
    product.

    Text that is empty or only spaces comes back as `None`, meaning there is nothing here
    to compare. Two blank names must never count as the same product.

    `casefold` rather than `lower`, because it does not depend on the language the machine
    is set to, so the same two documents compare the same way anywhere (NFR-1).
    """
    if value is None:
        return None
    collapsed = " ".join(value.split()).casefold()
    return collapsed or None


def _summarise(result: PriceReconciliation) -> str:
    """Put the whole comparison into a few short sentences.

    Built in a fixed order — what each document says, then whether the two can be compared
    at all, then what disagrees — so that two runs read alike and a representative learns
    where to look.
    """
    sentences = [
        f"ShipBob's records: {_line_count(result.shipbob_line_count)} "
        f"totalling {_money(result.shipbob_total, result.shipbob_currency)}.",
        _receipt_sentence(result),
        f"The two totals are {_money(result.total_difference, None)} apart.",
    ]

    currency_note = _currency_sentence(result.shipbob_currency, result.receipt_currency)
    if currency_note is not None:
        sentences.append(currency_note)

    if result.line_counts_differ:
        sentences.append(
            "The two documents do not list the same number of lines, so they may not be "
            "describing the same thing."
        )

    sentences.extend(_line_sentences(result))
    sentences.append(
        "Which of the two prices a claim should be settled against is not decided here; "
        "a person chooses."
        if result.has_findings
        else "Nothing here disagrees, so there is nothing to choose between."
    )
    return " ".join(sentences)


def _receipt_sentence(result: PriceReconciliation) -> str:
    """Say what the receipt shows, and whether its total was printed or added up.

    A receipt whose printed total is not what its own lines come to is the normal case, not
    a broken one — a discount, shipping or tax will do it — so both figures are said out
    loud rather than one being quietly preferred.
    """
    printed = _money(result.receipt_total, result.receipt_currency)
    if result.receipt_line_count == 0:
        if not result.receipt_total_is_stated:
            return "The customer's receipt: no lines were read off it at all."
        return (
            "The customer's receipt: no lines were read off it, only a printed total of "
            f"{printed}, which is the figure compared."
        )

    counted = _line_count(result.receipt_line_count)
    lines_total = _money(result.receipt_lines_total, result.receipt_currency)
    if not result.receipt_total_is_stated:
        return f"The customer's receipt: {counted} totalling {lines_total}."
    if result.receipt_total == result.receipt_lines_total:
        return (
            f"The customer's receipt: {counted} totalling {lines_total}, which is also the "
            "total printed on it."
        )
    return (
        f"The customer's receipt: {counted} totalling {lines_total}, but a printed total of "
        f"{printed}, which is the figure compared."
    )


def _currency_sentence(shipbob_currency: str | None, receipt_currency: str | None) -> str | None:
    """Warn, where it is warranted, that the two sides may not be in the same money.

    `None` when both documents named the same money, because then there is nothing to say.
    Everything else earns a sentence, including neither of them naming any — ShipBob's API
    has no currency field at all, so a dollar figure and a pound figure can be compared
    with nothing on either document admitting it.
    """
    if shipbob_currency is None and receipt_currency is None:
        return (
            "Neither document says what money its figures are in, so the two may not be "
            "comparable at all."
        )
    if shipbob_currency is None:
        return (
            f"Only the receipt says what money it is in ({receipt_currency}), so the two "
            "may not be comparable; nothing here converts between currencies."
        )
    if receipt_currency is None:
        return (
            f"Only ShipBob's records say what money they are in ({shipbob_currency}), so "
            "the two may not be comparable; nothing here converts between currencies."
        )
    if _comparable(shipbob_currency) != _comparable(receipt_currency):
        return (
            f"The two documents are not in the same money ({shipbob_currency} against "
            f"{receipt_currency}), so the gap between their totals is not a like-for-like "
            "figure; nothing here converts between currencies."
        )
    return None


def _line_sentences(result: PriceReconciliation) -> list[str]:
    """Say what the per-line comparison turned up, leaving out whatever it did not."""
    diverging = [line for line in result.lines if line.diverges]
    shipbob_only = [line for line in result.lines if line.kind is LineMatchKind.SHIPBOB_ONLY]
    receipt_only = [line for line in result.lines if line.kind is LineMatchKind.RECEIPT_ONLY]
    ambiguous = [line for line in result.lines if line.kind is LineMatchKind.AMBIGUOUS]

    sentences: list[str] = []
    if diverging:
        appears = "appears" if len(diverging) == 1 else "appear"
        sentences.append(
            f"{_line_count(len(diverging))} {appears} on both documents at a price the two "
            "do not agree on."
        )
    only_sentence = _only_on_one_side_sentence(len(shipbob_only), len(receipt_only))
    if only_sentence is not None:
        sentences.append(only_sentence)
    if ambiguous:
        sentences.append(
            f"{_line_count(len(ambiguous))} could be more than one line on the other "
            "document, so no comparison was made and nothing was chosen between."
        )
    return sentences


def _only_on_one_side_sentence(shipbob_only: int, receipt_only: int) -> str | None:
    """Say which lines only one of the two documents knows about.

    Only the side that actually has any is mentioned, and `None` comes back when neither
    does. Saying "no lines appear only in ShipBob's records" would be a sentence about
    nothing, and a summary full of those is one nobody reads to the end.
    """
    if shipbob_only and receipt_only:
        return (
            f"{_line_count(shipbob_only)} appear only in ShipBob's records and "
            f"{_line_count(receipt_only)} only on the receipt."
        )
    if shipbob_only:
        return f"{_line_count(shipbob_only)} appear only in ShipBob's records."
    if receipt_only:
        return f"{_line_count(receipt_only)} appear only on the receipt."
    return None


def _line_count(count: int) -> str:
    """Write a number of lines the way a person would say it out loud."""
    if count == 0:
        return "no lines"
    if count == 1:
        return "1 line"
    return f"{count} lines"


def _money(amount: Decimal, currency: str | None) -> str:
    """Write a figure as it should be read, with its currency label when there is one.

    The figure is written out exactly as it was calculated. Nothing is converted, and no
    symbol is invented for a label nobody gave.
    """
    if currency is None:
        return str(amount)
    return f"{amount} {currency}"
