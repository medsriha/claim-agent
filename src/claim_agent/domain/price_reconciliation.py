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
"""How precise a \"how far apart are these two prices\" figure is."""

_NOTHING = Decimal("0.00")
"""No money at all, written to the cent so every figure in a result reads alike."""


class LineMatchKind(StrEnum):
    """How one line on a document relates to the lines on the other document."""

    MATCHED_ON_SKU = "matched_on_sku"
    MATCHED_ON_NAME = "matched_on_name"
    SHIPBOB_ONLY = "shipbob_only"
    RECEIPT_ONLY = "receipt_only"
    AMBIGUOUS = "ambiguous"


class ReceiptLine(BaseModel):
    """One line as it is printed on the customer's own receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    sku: str | None = None
    quantity: int | None = None
    amount: Decimal


class LineComparison(BaseModel):
    """What was found about one product across the two documents."""

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
    """Everything found by holding the two documents up against each other."""

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

    @computed_field
    @property
    def same_currency(self) -> bool | None:
        """Whether the two sides are known to be in the same money."""
        if self.shipbob_currency is None or self.receipt_currency is None:
            return None
        return _comparable(self.shipbob_currency) == _comparable(self.receipt_currency)

    @computed_field
    @property
    def has_findings(self) -> bool:
        """Whether there is anything here about the prices or the lines worth reading."""
        if self.totals_diverge or self.line_counts_differ:
            return True
        return any(
            line.diverges
            or line.kind not in (LineMatchKind.MATCHED_ON_SKU, LineMatchKind.MATCHED_ON_NAME)
            for line in self.lines
        )

    @computed_field
    @property
    def summary(self) -> str:
        """The whole comparison in a few plain sentences, for a person to read."""
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
    """Compare what ShipBob says a shipment was worth with what the customer's receipt says."""
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
    """Which line was tied to which, built up one pass at a time."""

    matched: dict[int, tuple[int, LineMatchKind]] = field(default_factory=dict)
    ambiguous_shipbob: dict[int, tuple[str, ...]] = field(default_factory=dict)
    ambiguous_receipt: dict[int, tuple[str, ...]] = field(default_factory=dict)
    resolved_shipbob: set[int] = field(default_factory=set)
    resolved_receipt: set[int] = field(default_factory=set)


def _pair_up(
    shipbob_lines: Sequence[OrderLineItem], receipt_lines: Sequence[ReceiptLine]
) -> _Pairing:
    """Work out which line on one document is which line on the other."""
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
    """Pair up whatever the given keys tie together, and record what they confuse."""
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
    """Collect the positions of every line sharing a key, in the order they appear."""
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
    """Compare the two figures for one product that both documents agree exists."""
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
    """Express a gap as a share of the figure it is a gap from."""
    if reference == 0:
        return None
    return (gap / abs(reference)).quantize(_FRACTION_PLACES, rounding=ROUND_HALF_UP)


def _is_divergent(gap: Decimal, fraction: Decimal | None, threshold: Decimal) -> bool:
    """Say whether a gap between two prices is big enough to be worth mentioning."""
    if fraction is None:
        return gap > 0
    return fraction > threshold


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _comparable(value: str | None) -> str | None:
    """Reduce a name, a product code or a currency label to the form two are compared in."""
    if value is None:
        return None
    collapsed = " ".join(value.split()).casefold()
    return collapsed or None


def _summarise(result: PriceReconciliation) -> str:
    """Put the whole comparison into a few short sentences."""
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
    """Say what the receipt shows, and whether its total was printed or added up."""
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
    """Warn, where it is warranted, that the two sides may not be in the same money."""
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
    """Say which lines only one of the two documents knows about."""
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
    """Write a figure as it should be read, with its currency label when there is one."""
    if currency is None:
        return str(amount)
    return f"{amount} {currency}"
