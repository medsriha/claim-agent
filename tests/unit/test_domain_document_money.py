"""Reading money off a document, and checking the document against its own figures.

Two halves, and both of them exist because of what ShipBob's own sample claims contain.

**Reading a figure.** CASE-1001's order screenshot reads `£55.95` where ShipBob's record
for the same product says `52.00`. The pound sign is the most valuable thing on that
screenshot — it is the difference between a claim under the hundred-dollar cap and one
over it — so these tests are mostly about keeping it, and about refusing every figure
that cannot be read exactly rather than guessing at it (FR-1.13, FR-1.20).

**Checking a document.** CASE-1002's sales order does not add up on its own terms: three
items coming to `46.93`, a printed subtotal of `49.85`, a tax total printed as `0.00`, a
line reading "Shopify Tax $2.92" sitting among the items, and a final total of `49.42`.
That document has its own test below, with its real figures.

No requirement covers any of this; DESIGN.md records why it exists. The requirement ids
named in these tests are the nearest ones, not ones that describe the behaviour.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from claim_agent.domain.document_money import (
    ArithmeticCheck,
    DiscrepancyKind,
    check_document_arithmetic,
    parse_money_text,
)
from claim_agent.policy import Policy


def checked(
    *amounts: str,
    subtotal: str | None = None,
    tax: str | None = None,
    shipping: str | None = None,
    discount: str | None = None,
    total: str | None = None,
    tolerance: str | None = None,
) -> ArithmeticCheck:
    """Put a document's figures through the check, writing every one of them as text.

    Every figure goes in as a string and becomes an exact decimal here, which is the same
    route a figure read off a photograph takes. No test in this file writes a float.
    """
    policy = Policy() if tolerance is None else Policy(document_total_tolerance=Decimal(tolerance))
    return check_document_arithmetic(
        [Decimal(amount) for amount in amounts],
        subtotal=None if subtotal is None else Decimal(subtotal),
        tax=None if tax is None else Decimal(tax),
        shipping=None if shipping is None else Decimal(shipping),
        discount=None if discount is None else Decimal(discount),
        total=None if total is None else Decimal(total),
        policy=policy,
    )


# ---------------------------------------------------------------------------
# Reading a figure, and keeping what the document said about it
# ---------------------------------------------------------------------------


def test_fr_1_20_the_currency_symbol_on_case_1001s_screenshot_survives_the_reading() -> None:
    """FR-1.20: the pound sign decides whether this claim is over the cap or under it.

    ShipBob's record says 52.00 for the same product. Thrown away, the two figures are
    prices three dollars apart; kept, one of them is not in dollars at all.
    """
    reading = parse_money_text("£55.95")

    assert reading is not None
    assert reading.amount == Decimal("55.95")
    assert reading.currency_symbol == "£"
    assert reading.names_a_currency is True


def test_a_figure_with_no_currency_marker_is_reported_as_having_none() -> None:
    """A bare figure means the document never said, which is not the same as dollars.

    No API record carries a currency field anywhere, so a figure with nothing beside it
    is genuinely unknown. Whether an unknown one may be treated as dollars is a claim
    policy decision and is deliberately not made here.
    """
    reading = parse_money_text("49.42")

    assert reading is not None
    assert reading.amount == Decimal("49.42")
    assert reading.currency_symbol is None
    assert reading.currency_code is None
    assert reading.names_a_currency is False


def test_fr_1_13_a_symbol_is_never_turned_into_a_currency_code() -> None:
    """FR-1.13: three countries print a dollar sign, so choosing one would be a guess.

    The mark that was on the page is carried through as the mark that was on the page.
    """
    pounds = parse_money_text("£55.95")
    dollars = parse_money_text("$49.42")

    assert pounds is not None
    assert pounds.currency_code is None
    assert dollars is not None
    assert dollars.currency_code is None


def test_a_thousands_separator_is_read_in_either_convention() -> None:
    """The same amount written the American way and the European way reads the same.

    Both texts settle which separator is which on their own: the one that comes last is
    the decimal separator, and the other has to form proper groups of three.
    """
    american = parse_money_text("$1,234.56")
    european = parse_money_text("€1.234,56")

    assert american is not None
    assert american.amount == Decimal("1234.56")
    assert european is not None
    assert european.amount == Decimal("1234.56")


@pytest.mark.parametrize("written", ["1.234", "1,234"])
def test_fr_1_13_one_separator_with_three_digits_after_it_is_refused(written: str) -> None:
    """FR-1.13: a thousand and a figure to three decimal places look identical.

    Nothing in the text says which, and being wrong here is wrong by a factor of a
    thousand, on money. Refusing sends it to a person instead (NFR-4).
    """
    assert parse_money_text(written) is None


@pytest.mark.parametrize(
    "written",
    [
        "(12.34)",
        "12.34-",
        "-12.34",
        "($12.34)",
        "$-12.34",
    ],
)
def test_a_negative_is_read_however_the_document_wrote_it(written: str) -> None:
    """Brackets, a leading sign and a trailing sign all mean the same thing on a document.

    An invoice prints a credit in brackets; some accounting systems put the sign behind
    the figure. Reading only one of the three would turn a refund into a charge.
    """
    reading = parse_money_text(written)

    assert reading is not None
    assert reading.amount == Decimal("-12.34")


@pytest.mark.parametrize("written", ["USD 40.00", "40.00 USD", "usd 40.00"])
def test_a_three_letter_currency_code_is_read_from_either_side(written: str) -> None:
    """A document can name its currency in words instead of with a symbol."""
    reading = parse_money_text(written)

    assert reading is not None
    assert reading.amount == Decimal("40.00")
    assert reading.currency_code == "USD"
    assert reading.currency_symbol is None


def test_zero_is_money_and_is_read_as_money() -> None:
    """A printed zero is a fact about the document, not a failure to read it.

    CASE-1002's sales order prints its tax total as $0.00 while listing a tax of $2.92
    among its items, so a zero that reads as "nothing found" would hide the very
    contradiction worth reporting.
    """
    reading = parse_money_text("$0.00")

    assert reading is not None
    assert reading.amount == Decimal("0.00")
    assert reading.currency_symbol == "$"


def test_a_figure_written_with_no_pence_at_all_is_still_read() -> None:
    """Plenty of documents print a whole amount with no decimal part."""
    reading = parse_money_text("$55")

    assert reading is not None
    assert reading.amount == Decimal("55.00")


@pytest.mark.parametrize(
    "written",
    [
        "",
        "   ",
        "abc",
        "N/A",
        "-",
        "$",
        "12.34.56",
        "1,2,3",
        "12.345",
        "12.",
        "-12.34-",
        "(12.34",
        "12.34)",
        "Total: $49.42",
        "1,23,456.00",
        "50¢",
        "$40.00 USD",
    ],
)
def test_nfr_4_anything_that_cannot_be_read_exactly_comes_back_unread(written: str) -> None:
    """NFR-4: an unreadable figure goes to a person rather than becoming a guessed number.

    Each of these fails for its own reason, and every one of them is a reason to stop:
    it is not a figure at all, it has more decimal places than money has, its separators
    are placed in a way nobody writes, it carries two currency markers that would have to
    be reconciled, or it names a subunit that would be a hundred times too large the
    moment anything treated it as a whole one.
    """
    assert parse_money_text(written) is None


def test_the_text_as_it_appeared_is_kept_beside_what_we_made_of_it() -> None:
    """A reader can always see what was on the page, not only our reading of it."""
    reading = parse_money_text("  (£55.95)  ")

    assert reading is not None
    assert reading.raw == "  (£55.95)  "
    assert reading.amount == Decimal("-55.95")


def test_nfr_3_a_figure_is_never_turned_into_a_floating_point_number() -> None:
    """NFR-3: money is exact from the moment it is read, so no cent can drift.

    A tenth cannot be held exactly as a floating point number. Three of them added
    together come to exactly thirty hundredths here, and would not there.
    """
    reading = parse_money_text("0.10")

    assert reading is not None
    assert isinstance(reading.amount, Decimal)
    assert reading.amount * 3 == Decimal("0.30")


def test_nfr_1_the_same_text_reads_the_same_way_every_time() -> None:
    """NFR-1: nothing here reads a clock, and nothing here is chosen at random."""
    assert parse_money_text("£55.95") == parse_money_text("£55.95")


# ---------------------------------------------------------------------------
# Checking a document against its own figures
# ---------------------------------------------------------------------------


def test_case_1002s_sales_order_is_caught_disagreeing_with_itself_twice() -> None:
    """The real document: three items coming to 46.93, and two figures that do not fit.

    Its items are 9.95, 16.99 and 19.99. It prints a subtotal of 49.85, which is 2.92
    more than its items come to — and 2.92 is exactly the "Shopify Tax" line it also
    prints among the items while printing its tax total as 0.00. It then prints a final
    total of 49.42, which is 0.43 less than its own subtotal and tax.

    Nothing here works out why. Both gaps are reported with their figures, and a person
    decides what the document meant.
    """
    check = checked(
        "9.95",
        "16.99",
        "19.99",
        subtotal="49.85",
        tax="0.00",
        total="49.42",
    )

    assert check.line_total == Decimal("46.93")
    assert check.adds_up is False
    assert check.nothing_to_check is False
    assert check.checks_made == 2

    subtotal_gap, total_gap = check.discrepancies
    assert subtotal_gap.kind is DiscrepancyKind.LINES_DO_NOT_MATCH_SUBTOTAL
    assert subtotal_gap.printed == Decimal("49.85")
    assert subtotal_gap.recomputed == Decimal("46.93")
    assert subtotal_gap.difference == Decimal("2.92")

    assert total_gap.kind is DiscrepancyKind.PARTS_DO_NOT_MATCH_TOTAL
    assert total_gap.printed == Decimal("49.42")
    assert total_gap.recomputed == Decimal("49.85")
    assert total_gap.difference == Decimal("-0.43")


def test_a_disagreement_says_in_words_what_it_found() -> None:
    """A representative should not have to do the subtraction to see the problem.

    The sentence carries no currency symbol on purpose: this check never learns what
    currency the document is in, and printing one it never saw would invent the fact the
    reading half of this module works hardest to keep.
    """
    check = checked("9.95", "16.99", "19.99", subtotal="49.85")

    assert check.discrepancies[0].explanation == (
        "The document prints a subtotal of 49.85, but its 3 lines come to 46.93 — "
        "a difference of 2.92."
    )
    assert "$" not in check.discrepancies[0].explanation


def test_a_document_that_adds_up_is_reported_as_adding_up() -> None:
    """The ordinary case: every printed figure agrees with the ones it is built from."""
    check = checked(
        "38.00",
        "52.00",
        subtotal="90.00",
        tax="7.43",
        shipping="5.00",
        total="102.43",
    )

    assert check.discrepancies == ()
    assert check.adds_up is True
    assert check.nothing_to_check is False
    assert check.checks_made == 2


def test_nfr_4_a_document_printing_no_totals_is_nothing_to_check_rather_than_a_failure() -> None:
    """NFR-4: "we could not check" and "we checked and it is fine" must not read alike.

    A photograph that shows the items but crops the totals is an ordinary thing to be
    handed. Nothing is raised, the items are still added up, and the result says plainly
    that it cannot vouch for anything.
    """
    check = checked("9.95", "16.99")

    assert check.line_total == Decimal("26.94")
    assert check.nothing_to_check is True
    assert check.adds_up is False
    assert check.discrepancies == ()


def test_a_receipt_with_a_total_but_no_subtotal_is_still_checked() -> None:
    """With no subtotal printed, the items themselves are what the total is held against.

    Otherwise the simplest documents — a till receipt listing items and one total — would
    be the ones nothing ever checked.
    """
    check = checked("9.95", "16.99", tax="1.50", total="28.44")

    assert check.checks_made == 1
    assert check.adds_up is True


def test_a_discount_brings_the_total_below_what_the_items_come_to() -> None:
    """CASE-1003's invoice takes 14.99 off, and the document is right to be lower.

    A discount is the ordinary reason a total is less than the items add up to, so
    ignoring it would report a fault on a perfectly good document.
    """
    check = checked("149.98", subtotal="149.98", discount="14.99", total="134.99")

    assert check.adds_up is True
    assert check.checks_made == 2


def test_the_sign_a_discount_is_written_with_does_not_change_what_it_does() -> None:
    """A discount printed as -14.99 and one printed as 14.99 are the same reduction.

    Documents print it both ways. Treating the minus sign as arithmetic would report a
    fault that exists only in how the figure was typed.
    """
    positive = checked("149.98", subtotal="149.98", discount="14.99", total="134.99")
    negative = checked("149.98", subtotal="149.98", discount="-14.99", total="134.99")

    assert positive.adds_up is True
    assert negative.adds_up is True


def test_a_difference_is_positive_when_the_document_claims_more_than_it_can_support() -> None:
    """The direction matters more than the size: this is the one that costs money."""
    check = checked("10.00", "10.00", subtotal="25.00")

    assert check.discrepancies[0].difference == Decimal("5.00")


def test_fr_0_7_rounding_within_the_allowance_is_not_a_disagreement() -> None:
    """FR-0.7, NFR-7: how much rounding is forgiven is a claim policy value.

    A penny either way is how documents round. Two pence is not, on the default
    allowance, and a service run with a looser allowance forgives it — which is the point
    of the value being a setting rather than a number written into this check.
    """
    on_the_boundary = checked("10.00", "10.00", subtotal="20.01")
    just_past_it = checked("10.00", "10.00", subtotal="20.02")
    forgiven = checked("10.00", "10.00", subtotal="20.02", tolerance="0.02")

    assert on_the_boundary.adds_up is True
    assert on_the_boundary.tolerance == Decimal("0.01")
    assert just_past_it.adds_up is False
    assert just_past_it.discrepancies[0].difference == Decimal("0.02")
    assert forgiven.adds_up is True
    assert forgiven.tolerance == Decimal("0.02")


def test_a_document_with_no_items_read_off_it_still_has_its_totals_checked() -> None:
    """A photograph too blurred to list the items can still show the totals disagreeing."""
    check = checked(subtotal="49.85", tax="0.00", total="49.42")

    assert check.line_total == Decimal("0.00")
    assert check.checks_made == 1
    assert check.discrepancies[0].kind is DiscrepancyKind.PARTS_DO_NOT_MATCH_TOTAL


def test_nfr_1_the_same_document_is_checked_the_same_way_every_time() -> None:
    """NFR-1: the arithmetic is exact and the order of the findings is fixed."""
    first = checked("9.95", "16.99", "19.99", subtotal="49.85", tax="0.00", total="49.42")
    second = checked("9.95", "16.99", "19.99", subtotal="49.85", tax="0.00", total="49.42")

    assert first == second
