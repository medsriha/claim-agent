from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.reimbursement import CENTS
from claim_agent.policy import Policy

READABLE_CURRENCY_SYMBOLS = "$£€¥₹"
"""The currency symbols a figure may be written with.

The same symbols the merchant email is searched for, minus the cent sign. That file
looks for money in order to **refuse** it, so it is deliberately broad and includes
`¢`; this file looks for money in order to **read** it, and a figure written in a
subunit would be a hundred times too large the moment anything treated it as a whole
one. `50¢` is therefore refused rather than read as fifty of anything.

None of these symbols is treated as naming a country. `$` is written by the United
States, Canada and Australia alike, and `£` by more than one country too, so a symbol
is carried through as the mark that was on the page and never turned into a currency
code. What it is worth in dollars is somebody else's decision.
"""

READABLE_CURRENCY_CODES = ("USD", "GBP", "EUR", "CAD", "AUD", "JPY")
"""The three-letter currency codes recognised beside a figure.

The same six the merchant email looks for, so the two files agree on what counts as a
currency code. Recognising a code here is only about **reading** the text: a code with
no exchange rate behind it is still read correctly and still has to be priced by
somebody who has one.
"""

_PLAIN_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?")
"""What is left once a sign and a currency marker have been taken off a figure.

Digits, with dots and commas allowed in between, and a digit at each end. Anything else
— a space, a letter, a second sign, a stray bracket — means the text was not a single
figure, and a single figure is the only thing this file claims to read.
"""

_LEADING_CODE = re.compile(rf"^({'|'.join(READABLE_CURRENCY_CODES)})\s*", re.IGNORECASE)
_TRAILING_CODE = re.compile(rf"\s*({'|'.join(READABLE_CURRENCY_CODES)})$", re.IGNORECASE)

_MINUS_SIGNS = ("-", "\u2212")
"""The characters that mean "negative" in front of or behind a figure.

The plain hyphen, and the true minus sign that word processors and some accounting
systems print instead. They look almost identical on a page, so treating only one of
them as a sign would turn a credit into a charge depending on which program produced the
document. The second is written as its character number because the two are impossible
to tell apart in code.
"""


class MoneyReading(BaseModel):
    """One figure read off a document, with whatever named its currency kept beside it.

    `raw` is the text exactly as it was handed in, spaces and brackets included, so a
    reader can always see what was on the page rather than what we made of it.

    `amount` is the number, as an exact decimal, held to the cent. Holding it there can
    never change the figure, because anything written to more than two decimal places is
    refused before it becomes a reading; it only means `$55` and `$55.95` come back
    looking like the same kind of thing. It is negative when the document wrote it as a
    negative — a refund, a credit, or a discount line — however the document wrote it.

    `currency_symbol` is the mark that was printed, `£` or `$` or `€`, and `None` when
    no mark was printed. `currency_code` is the three-letter code, and `None` when none
    was written. Both are `None` for a bare figure such as `49.42`, and that is the
    interesting case: it means the document never said what currency this is, not that
    it is dollars.

    **Neither field is ever inferred from the other.** A pound sign does not become
    `GBP` here, because more than one country prints one; a dollar sign does not become
    `USD`, because three do. Deciding which is exactly the kind of narrowing this system
    is not allowed to do on its own (FR-1.13).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    amount: Decimal
    currency_symbol: str | None = None
    currency_code: str | None = None

    @property
    def names_a_currency(self) -> bool:
        """True when the document said what currency this figure is in.

        False means nobody has said, which is the state a claim should not be priced in
        without a person or a stated assumption behind it.
        """
        return self.currency_symbol is not None or self.currency_code is not None


class DiscrepancyKind(StrEnum):
    """The ways a document can disagree with itself.

    `LINES_DO_NOT_MATCH_SUBTOTAL` means the items listed on the document do not add up
    to the subtotal it prints. Something is on the document that is not in its list, or
    something in its list is not in its subtotal.

    `PARTS_DO_NOT_MATCH_TOTAL` means the figures the document prints — its subtotal, its
    tax, its shipping, its discount — do not add up to the final total it prints.
    """

    LINES_DO_NOT_MATCH_SUBTOTAL = "lines_do_not_match_subtotal"
    PARTS_DO_NOT_MATCH_TOTAL = "parts_do_not_match_total"


class ArithmeticDiscrepancy(BaseModel):
    """One place where a document's own figures do not agree.

    `printed` is what the document says. `recomputed` is what its other figures actually
    come to. `difference` is `printed` minus `recomputed`, so a positive difference means
    the document claims more than its own figures support — the direction that costs
    money, and the one worth reading first.

    `explanation` says the same thing in a sentence a representative can read without
    working anything out. It deliberately carries **no currency symbol**: this check
    never learns what currency the document is in, and printing a `$` it did not see
    would be inventing the one fact the reading half of this file works hardest to keep.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DiscrepancyKind
    printed: Decimal
    recomputed: Decimal
    difference: Decimal
    explanation: str


class ArithmeticCheck(BaseModel):
    """What came of recomputing a document's totals from its own figures.

    `line_total` is what the items on the document add up to, which is worth having even
    when nothing could be compared to it. It is `0.00` when no lines were given.

    `checks_made` is how many comparisons were actually possible. A document that prints
    no totals at all supports none, and that is an ordinary answer rather than a failure:
    there was simply nothing to check.

    `discrepancies` lists every disagreement found, in the order the document's own
    figures build on each other — the lines first, then the total. Empty means nothing
    was found, which is not the same as everything being right; read `checks_made` too.

    `tolerance` is how far a figure was allowed to sit from the recomputed one before it
    counted as a disagreement, carried here so a reader can see what was forgiven.
    """

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
        """True when something was checked and all of it agreed.

        False both when a disagreement was found and when nothing could be checked at
        all. The two are told apart by `nothing_to_check`, and they are kept apart on
        purpose: "we checked and it is fine" and "we could not check" must never read the
        same way to somebody deciding whether to trust a total (NFR-4).
        """
        return self.checks_made > 0 and not self.discrepancies


def parse_money_text(raw: str) -> MoneyReading | None:
    """Read one figure of money written as text, or say that it cannot be read.

    This is how a price on a photograph becomes a number the system can work with
    without losing what the document said about it. The currency mark is kept, because
    on ShipBob's own sample data it is the difference between a claim under the
    reimbursement cap and one over it (FR-1.20).

    What it reads:

    - a figure with a symbol in front or behind it, `£55.95` or `55.95 €`;
    - a figure with a three-letter code in front or behind it, `USD 40.00`, `40.00 USD`;
    - a bare figure, `49.42`, which comes back with no currency at all rather than being
      assumed to be dollars;
    - a negative written any of the three ways a document writes one: in brackets,
      `(12.34)`, which is how an invoice prints a credit; with the sign in front,
      `-12.34`; or with the sign behind, `12.34-`, which some accounting systems print;
    - thousands separators, in either convention, when the text settles which is which:
      `1,234.56` and `1.234,56` both come back as one thousand two hundred and
      thirty-four and fifty-six.

    What it refuses, and why refusing is the right answer:

    - **`1.234` and `1,234` on their own.** One separator with three digits after it is
      either a thousand or a figure written to three decimal places, and nothing in the
      text says which. Reading it wrongly is a mistake by a factor of a thousand, on
      money, so it is not read at all (FR-1.13).
    - **more than two decimal places.** `12.345` is not money to the cent, and rounding
      it here would be this file deciding something a person should decide.
    - **two currency markers at once.** `$40.00 USD` is refused along with `£40.00 USD`,
      because reconciling markers that agree would mean also reconciling markers that
      contradict each other.
    - **a subunit.** `50¢` names a hundredth of something, and a figure that is silently
      a hundred times too large is the worst thing this function could produce.
    - **anything that is not a single figure.** `Total: $49.42` is a sentence, and
      picking the money out of a sentence means deciding which number is the money.

    How this relates to the money search in the merchant email: the two look for the same
    thing in opposite directions, and they deliberately do not share a pattern. That one
    hunts for **anything** that might be money in wording a model wrote, so that none of
    it reaches a merchant, and it is broad on purpose — broad enough to include number
    words such as "fifty-two dollars", and to accept one known hole, the word "pounds",
    which is a weight as often as a currency. This one reads **one** figure and must be
    exact, so breadth here would mean guessing. Sharing a pattern would mean a change
    made to loosen one silently loosened the other, in the direction that lets money
    through. What is shared is the reasoning and the symbol list, written out here rather
    than imported.

    Args:
        raw: The text as it was read off the document, with any spaces around it.

    Returns:
        The figure, its currency mark if it had one, and the exact number. `None` when
        the text is not a single readable figure, which is a real answer and not an
        error: the caller requests representative clarification or asks for a clearer photograph rather than
        proceeding on a guess (NFR-4).
    """
    text = raw.strip()
    if not text:
        return None

    text, in_brackets = _strip_brackets(text)
    text, signed = _strip_minus_sign(text)
    text, symbol, code = _strip_currency_marker(text)
    if not signed:
        # Some systems print the sign inside the symbol, "$-12.34", so the sign is
        # looked for once more now that the symbol is out of the way — and only once,
        # so that "-12.34-" stays unreadable rather than becoming a number.
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
    """Add a document's own figures up again, and report every place it disagrees.

    A total on a photograph is not a fact. It is a number somebody's eyes or a model's
    guess produced from an image, printed by a system that may itself have got it wrong.
    One of ShipBob's own sample documents does exactly that: three items adding to
    `46.93`, a printed subtotal of `49.85`, a tax total printed as `0.00`, and a final
    total of `49.42`. Believing any one of those figures would put the wrong number in
    front of a representative, so all of them are checked against each other.

    The arithmetic happens here rather than in the investigation's answer, for the reason
    the reimbursement cap exists: a figure that decides money has to be one a person can
    redo and get the same result (NFR-1).

    Two links are checked, each once, following the chain a document builds:

    1. **The items against the printed subtotal.** Only when there are items and the
       document prints a subtotal.
    2. **The printed parts against the printed total** — the subtotal, plus tax, plus
       shipping, less the discount. When the document prints no subtotal, the items are
       used as the starting point instead, so a simple receipt is still checked.

    Checking the second link once, from the subtotal when there is one, is deliberate.
    A document with a wrong subtotal would otherwise report the same fault twice over
    and leave a reader working out whether it was one problem or two.

    Args:
        line_amounts: What each item on the document costs, as exact decimals. A line
            the document prints as a negative — a returned item, a credit — belongs here
            as a negative. An empty sequence means no items could be read, which skips
            the first link rather than failing.
        subtotal: The subtotal the document prints, or `None` if it prints none.
        tax: The tax the document prints, or `None`. Treated as added to the total.
        shipping: The shipping the document prints, or `None`. Also added.
        discount: What the document takes off, or `None`. Its sign is ignored: a
            discount printed as `14.99` and one printed as `-14.99` mean the same
            reduction, and treating the minus as arithmetic would report a fault that
            exists only in how the figure was written.
        total: The final total the document prints, or `None` if it prints none.
        policy: Read for how far a printed figure may sit from the recomputed one before
            the document is called inconsistent, so the allowance is a value somebody
            can see and change rather than a number buried here (FR-0.7, NFR-7).

    Returns:
        What the items add up to, how many comparisons were possible, and every
        disagreement found. Nothing is raised: a document that prints no totals is not a
        failure, it is a document with nothing to check, and the result says so.
    """
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
            # The sign a discount is written with says nothing about its direction; a
            # discount only ever comes off.
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
    """Take the brackets off a figure written as `(12.34)`, and say it was negative.

    Brackets around a figure are how an invoice prints a credit. Only a matching pair
    counts: half a pair means the text was cut off or misread, and a figure we are not
    sure we have all of is not a figure worth reading.
    """
    if len(text) > 2 and text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip(), True
    return text, False


def _strip_minus_sign(text: str) -> tuple[str, bool]:
    """Take a minus sign off the front or the back of a figure, and say it was there.

    Only one sign is taken, and only from one end, so `-12.34-` keeps a sign wherever it
    is stripped from and stops being a readable figure. Two signs on one number means
    somebody misread the page.
    """
    for sign in _MINUS_SIGNS:
        if text.startswith(sign):
            return text[len(sign) :].strip(), True
        if text.endswith(sign):
            return text[: -len(sign)].strip(), True
    return text, False


def _strip_currency_marker(text: str) -> tuple[str, str | None, str | None]:
    """Take the one currency mark off a figure, and say which mark it was.

    Exactly one marker is taken, from whichever end carries it. That is why `$40.00 USD`
    comes back with the symbol removed and `40.00 USD` left over, which then fails to
    read as a number — a figure that names its currency twice is refused rather than
    reconciled, because the same rule has to cover `£40.00 USD`, where the two markers
    contradict each other and no reading of it is safe.

    Returns the text with the marker gone, the symbol if it was a symbol, and the code
    in capitals if it was a code. Both are `None` when the figure carried no marker.
    """
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
    """Read the digits of a figure, working out which separator means what.

    The whole difficulty is that a dot and a comma each mean two different things
    depending on where the document was printed. The text itself settles it whenever it
    can, and where it cannot, nothing is read:

    - no separator at all: the digits are the number.
    - both a dot and a comma: whichever comes **last** is the decimal separator, and the
      other has to form proper groups of three. This is how `1,234.56` and `1.234,56`
      are both read correctly.
    - one separator, appearing more than once: it can only be grouping, and every group
      has to be three digits long.
    - one separator with one or two digits after it: it is the decimal separator,
      because no thousands group is one or two digits long.
    - one separator with exactly three digits after it: **unreadable**. `1.234` is a
      thousand in one country and a figure to three decimal places in another, and
      guessing would be wrong by a factor of a thousand.
    - anything else after the separator — none, or four or more digits — is not money to
      the cent and is not read.

    Returns the number as an exact decimal, or `None` when it cannot be read safely.
    """
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
    """Take the thousands separators out of a run of digits, if they are placed properly.

    Proper means what everybody writes: one to three digits, then groups of exactly
    three. `1,234,567` joins up; `1,23,456` and `12.34.56` do not, and text that does not
    is text nobody has read correctly.

    Returns the digits with the separators gone, or `None` if the grouping is not proper.
    """
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
    """Hold one printed figure against what the document's other figures come to.

    A gap no larger than the tolerance is not reported at all: documents round, and a
    penny of rounding is not a document contradicting itself. A gap larger than it is
    reported with both figures, so a reader can see the size of the problem rather than
    being told there is one.

    Returns `None` when the two agree.
    """
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
    """List, in words, which of the document's figures went into the total we recomputed.

    Only the figures that were actually there are named. Telling a reader that "the
    subtotal, tax, shipping and discount" came to something, when the document printed
    no shipping at all, would describe a sum nobody performed.
    """
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
    """Write a figure the way it appears in a sentence a representative reads.

    Rounded to the cent and handed over as text. No currency symbol: this check never
    learns what currency the document is in, and a `$` it never saw would be an invention.
    """
    return str(_to_cents(value))


def _to_cents(value: Decimal) -> Decimal:
    """Round money to the nearest cent, half a cent going up.

    The same rounding, and the same shared definition of a cent, that a recommended
    amount uses, so two figures a representative compares were reached the same way.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)
