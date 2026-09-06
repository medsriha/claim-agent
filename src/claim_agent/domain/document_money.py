from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.reimbursement import CENTS
from claim_agent.policy import Policy

READABLE_CURRENCY_SYMBOLS = "$£€¥₹"
"""The currency symbols a figure may be written with."""

READABLE_CURRENCY_CODES = ("USD", "GBP", "EUR", "CAD", "AUD", "JPY")
"""The three-letter currency codes recognised beside a figure."""

_PLAIN_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?")
"""What is left once a sign and a currency marker have been taken off a figure."""

_LEADING_CODE = re.compile(rf"^({'|'.join(READABLE_CURRENCY_CODES)})\s*", re.IGNORECASE)
_TRAILING_CODE = re.compile(rf"\s*({'|'.join(READABLE_CURRENCY_CODES)})$", re.IGNORECASE)

_MINUS_SIGNS = ("-", "\u2212")
"""The characters that mean \"negative\" in front of or behind a figure."""


class MoneyReading(BaseModel):
    """One figure read off a document, with whatever named its currency kept beside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    amount: Decimal
    currency_symbol: str | None = None
    currency_code: str | None = None

    @property
    def names_a_currency(self) -> bool:
        """True when the document said what currency this figure is in."""
        return self.currency_symbol is not None or self.currency_code is not None


class DiscrepancyKind(StrEnum):
    """The ways a document can disagree with itself."""

    LINES_DO_NOT_MATCH_SUBTOTAL = "lines_do_not_match_subtotal"
    PARTS_DO_NOT_MATCH_TOTAL = "parts_do_not_match_total"


class ArithmeticDiscrepancy(BaseModel):
    """One place where a document's own figures do not agree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DiscrepancyKind
    printed: Decimal
    recomputed: Decimal
    difference: Decimal
    explanation: str


class ArithmeticCheck(BaseModel):
    """What came of recomputing a document's totals from its own figures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_total: Decimal
    checks_made: int
    tolerance: Decimal
    discrepancies: tuple[ArithmeticDiscrepancy, ...] = ()

    @property
    def nothing_to_check(self) -> bool:
        """True when the document printed nothing that could be compared to anything."""
        return self.checks_made == 0

    @property
    def adds_up(self) -> bool:
        """True when something was checked and all of it agreed."""
        return self.checks_made > 0 and not self.discrepancies


def parse_money_text(raw: str) -> MoneyReading | None:
    """Read one figure of money written as text, or say that it cannot be read."""
    text = raw.strip()
    if not text:
        return None

    text, in_brackets = _strip_brackets(text)
    text, signed = _strip_minus_sign(text)
    text, symbol, code = _strip_currency_marker(text)
    if not signed:
        text, signed = _strip_minus_sign(text)

    value = _read_number(text.strip())
    if value is None:
        return None

    negative = in_brackets or signed
    return MoneyReading(
        raw=raw,
        amount=_to_cents(-value if negative else value),
        currency_symbol=symbol,
        currency_code=code,
    )


def check_document_arithmetic(
    line_amounts: Sequence[Decimal],
    *,
    subtotal: Decimal | None = None,
    tax: Decimal | None = None,
    shipping: Decimal | None = None,
    discount: Decimal | None = None,
    total: Decimal | None = None,
    policy: Policy,
) -> ArithmeticCheck:
    """Add a document's own figures up again, and report every place it disagrees."""
    tolerance = policy.document_total_tolerance
    line_total = _to_cents(sum(line_amounts, start=Decimal("0")))

    discrepancies: list[ArithmeticDiscrepancy] = []
    checks_made = 0

    if line_amounts and subtotal is not None:
        checks_made += 1
        found = _compare(
            kind=DiscrepancyKind.LINES_DO_NOT_MATCH_SUBTOTAL,
            printed=_to_cents(subtotal),
            recomputed=line_total,
            tolerance=tolerance,
            printed_name="a subtotal",
            recomputed_name=_name_the_lines(len(line_amounts)),
        )
        if found is not None:
            discrepancies.append(found)

    starting_point = subtotal if subtotal is not None else (line_total if line_amounts else None)
    if total is not None and starting_point is not None:
        checks_made += 1
        recomputed = _to_cents(
            starting_point
            + (tax or Decimal("0"))
            + (shipping or Decimal("0"))
            - abs(discount or Decimal("0"))
        )
        found = _compare(
            kind=DiscrepancyKind.PARTS_DO_NOT_MATCH_TOTAL,
            printed=_to_cents(total),
            recomputed=recomputed,
            tolerance=tolerance,
            printed_name="a total",
            recomputed_name=_name_the_parts(
                from_subtotal=subtotal is not None,
                tax=tax,
                shipping=shipping,
                discount=discount,
            ),
        )
        if found is not None:
            discrepancies.append(found)

    return ArithmeticCheck(
        line_total=line_total,
        checks_made=checks_made,
        tolerance=tolerance,
        discrepancies=tuple(discrepancies),
    )


def _strip_brackets(text: str) -> tuple[str, bool]:
    """Take the brackets off a figure written as `(12.34)`, and say it was negative."""
    if len(text) > 2 and text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip(), True
    return text, False


def _strip_minus_sign(text: str) -> tuple[str, bool]:
    """Take a minus sign off the front or the back of a figure, and say it was there."""
    for sign in _MINUS_SIGNS:
        if text.startswith(sign):
            return text[len(sign) :].strip(), True
        if text.endswith(sign):
            return text[: -len(sign)].strip(), True
    return text, False


def _strip_currency_marker(text: str) -> tuple[str, str | None, str | None]:
    """Take the one currency mark off a figure, and say which mark it was."""
    if text and text[0] in READABLE_CURRENCY_SYMBOLS:
        return text[1:].strip(), text[0], None
    if text and text[-1] in READABLE_CURRENCY_SYMBOLS:
        return text[:-1].strip(), text[-1], None

    leading = _LEADING_CODE.match(text)
    if leading is not None:
        return text[leading.end() :].strip(), None, leading.group(1).upper()

    trailing = _TRAILING_CODE.search(text)
    if trailing is not None:
        return text[: trailing.start()].strip(), None, trailing.group(1).upper()

    return text, None, None


def _read_number(digits: str) -> Decimal | None:
    """Read the digits of a figure, working out which separator means what."""
    if _PLAIN_NUMBER.fullmatch(digits) is None:
        return None

    separators = {character for character in digits if character in ".,"}
    if not separators:
        return Decimal(digits)

    if len(separators) == 2:
        decimal_point = "." if digits.rindex(".") > digits.rindex(",") else ","
        grouping = "," if decimal_point == "." else "."
        return _read_grouped_number(digits, decimal_point=decimal_point, grouping=grouping)

    only = separators.pop()
    if digits.count(only) > 1:
        whole = _join_groups(digits, only)
        return None if whole is None else Decimal(whole)

    head, tail = digits.split(only)
    if len(tail) == 3:
        return None
    if not 1 <= len(tail) <= 2 or not head.isdigit():
        return None
    return Decimal(f"{head}.{tail}")


def _read_grouped_number(digits: str, *, decimal_point: str, grouping: str) -> Decimal | None:
    """Read a figure that uses one separator for grouping and the other for decimals."""
    head, tail = digits.rsplit(decimal_point, 1)
    if not 1 <= len(tail) <= 2 or not tail.isdigit():
        return None
    whole = _join_groups(head, grouping)
    if whole is None:
        return None
    return Decimal(f"{whole}.{tail}")


def _join_groups(text: str, separator: str) -> str | None:
    """Take the thousands separators out of a run of digits, if they are placed properly."""
    parts = text.split(separator)
    if not all(part.isdigit() for part in parts):
        return None
    first, rest = parts[0], parts[1:]
    if not 1 <= len(first) <= 3:
        return None
    if any(len(part) != 3 for part in rest):
        return None
    return "".join(parts)


def _compare(
    *,
    kind: DiscrepancyKind,
    printed: Decimal,
    recomputed: Decimal,
    tolerance: Decimal,
    printed_name: str,
    recomputed_name: str,
) -> ArithmeticDiscrepancy | None:
    """Hold one printed figure against what the document's other figures come to."""
    difference = printed - recomputed
    if abs(difference) <= tolerance:
        return None
    return ArithmeticDiscrepancy(
        kind=kind,
        printed=printed,
        recomputed=recomputed,
        difference=difference,
        explanation=(
            f"The document prints {printed_name} of {_as_text(printed)}, but "
            f"{recomputed_name} come to {_as_text(recomputed)} — a difference of "
            f"{_as_text(abs(difference))}."
        ),
    )


def _name_the_lines(how_many: int) -> str:
    """Say how many items were added up, so a sentence can name them: "its 3 lines"."""
    return "its 1 line" if how_many == 1 else f"its {how_many} lines"


def _name_the_parts(
    *,
    from_subtotal: bool,
    tax: Decimal | None,
    shipping: Decimal | None,
    discount: Decimal | None,
) -> str:
    """List, in words, which of the document's figures went into the total we recomputed."""
    parts = ["its subtotal" if from_subtotal else "its lines"]
    if tax is not None:
        parts.append("tax")
    if shipping is not None:
        parts.append("shipping")
    if discount is not None:
        parts.append("discount")
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _as_text(value: Decimal) -> str:
    """Write a figure the way it appears in a sentence a representative reads."""
    return str(_to_cents(value))


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)
