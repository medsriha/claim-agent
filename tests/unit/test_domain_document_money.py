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


def test_fr_1_20_the_currency_symbol_on_case_1001s_screenshot_survives_the_reading() -> None:
    reading = parse_money_text("£55.95")

    assert reading is not None
    assert reading.amount == Decimal("55.95")
    assert reading.currency_symbol == "£"
    assert reading.names_a_currency is True


def test_a_figure_with_no_currency_marker_is_reported_as_having_none() -> None:
    reading = parse_money_text("49.42")

    assert reading is not None
    assert reading.amount == Decimal("49.42")
    assert reading.currency_symbol is None
    assert reading.currency_code is None
    assert reading.names_a_currency is False


def test_fr_1_13_a_symbol_is_never_turned_into_a_currency_code() -> None:
    pounds = parse_money_text("£55.95")
    dollars = parse_money_text("$49.42")

    assert pounds is not None
    assert pounds.currency_code is None
    assert dollars is not None
    assert dollars.currency_code is None


def test_a_thousands_separator_is_read_in_either_convention() -> None:
    american = parse_money_text("$1,234.56")
    european = parse_money_text("€1.234,56")

    assert american is not None
    assert american.amount == Decimal("1234.56")
    assert european is not None
    assert european.amount == Decimal("1234.56")


@pytest.mark.parametrize("written", ["1.234", "1,234"])
def test_fr_1_13_one_separator_with_three_digits_after_it_is_refused(written: str) -> None:
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
    reading = parse_money_text(written)

    assert reading is not None
    assert reading.amount == Decimal("-12.34")


@pytest.mark.parametrize("written", ["USD 40.00", "40.00 USD", "usd 40.00"])
def test_a_three_letter_currency_code_is_read_from_either_side(written: str) -> None:
    reading = parse_money_text(written)

    assert reading is not None
    assert reading.amount == Decimal("40.00")
    assert reading.currency_code == "USD"
    assert reading.currency_symbol is None


def test_zero_is_money_and_is_read_as_money() -> None:
    reading = parse_money_text("$0.00")

    assert reading is not None
    assert reading.amount == Decimal("0.00")
    assert reading.currency_symbol == "$"


def test_a_figure_written_with_no_pence_at_all_is_still_read() -> None:
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
    assert parse_money_text(written) is None


def test_the_text_as_it_appeared_is_kept_beside_what_we_made_of_it() -> None:
    reading = parse_money_text("  (£55.95)  ")

    assert reading is not None
    assert reading.raw == "  (£55.95)  "
    assert reading.amount == Decimal("-55.95")


def test_nfr_3_a_figure_is_never_turned_into_a_floating_point_number() -> None:
    reading = parse_money_text("0.10")

    assert reading is not None
    assert isinstance(reading.amount, Decimal)
    assert reading.amount * 3 == Decimal("0.30")


def test_nfr_1_the_same_text_reads_the_same_way_every_time() -> None:
    assert parse_money_text("£55.95") == parse_money_text("£55.95")


def test_case_1002s_sales_order_is_caught_disagreeing_with_itself_twice() -> None:
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
    check = checked("9.95", "16.99", "19.99", subtotal="49.85")

    assert check.discrepancies[0].explanation == (
        "The document prints a subtotal of 49.85, but its 3 lines come to 46.93 — "
        "a difference of 2.92."
    )
    assert "$" not in check.discrepancies[0].explanation


def test_a_document_that_adds_up_is_reported_as_adding_up() -> None:
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
    check = checked("9.95", "16.99")

    assert check.line_total == Decimal("26.94")
    assert check.nothing_to_check is True
    assert check.adds_up is False
    assert check.discrepancies == ()


def test_a_receipt_with_a_total_but_no_subtotal_is_still_checked() -> None:
    check = checked("9.95", "16.99", tax="1.50", total="28.44")

    assert check.checks_made == 1
    assert check.adds_up is True


def test_a_discount_brings_the_total_below_what_the_items_come_to() -> None:
    check = checked("149.98", subtotal="149.98", discount="14.99", total="134.99")

    assert check.adds_up is True
    assert check.checks_made == 2


def test_the_sign_a_discount_is_written_with_does_not_change_what_it_does() -> None:
    positive = checked("149.98", subtotal="149.98", discount="14.99", total="134.99")
    negative = checked("149.98", subtotal="149.98", discount="-14.99", total="134.99")

    assert positive.adds_up is True
    assert negative.adds_up is True


def test_a_difference_is_positive_when_the_document_claims_more_than_it_can_support() -> None:
    check = checked("10.00", "10.00", subtotal="25.00")

    assert check.discrepancies[0].difference == Decimal("5.00")


def test_fr_0_7_rounding_within_the_allowance_is_not_a_disagreement() -> None:
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
    check = checked(subtotal="49.85", tax="0.00", total="49.42")

    assert check.line_total == Decimal("0.00")
    assert check.checks_made == 1
    assert check.discrepancies[0].kind is DiscrepancyKind.PARTS_DO_NOT_MATCH_TOTAL


def test_nfr_1_the_same_document_is_checked_the_same_way_every_time() -> None:
    first = checked("9.95", "16.99", "19.99", subtotal="49.85", tax="0.00", total="49.42")
    second = checked("9.95", "16.99", "19.99", subtotal="49.85", tax="0.00", total="49.42")

    assert first == second
