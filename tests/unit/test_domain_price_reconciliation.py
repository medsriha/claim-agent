from __future__ import annotations

from decimal import Decimal

from tests.fixtures.shipbob import ORDER_1001, ORDER_1002, ORDER_1003, ORDER_1004

from claim_agent.domain.models import Order, OrderLineItem
from claim_agent.domain.price_reconciliation import (
    LineMatchKind,
    PriceReconciliation,
    ReceiptLine,
    reconcile_prices,
)
from claim_agent.policy import Policy


def shipbob_lines_of(order_payload: dict[str, object]) -> tuple[OrderLineItem, ...]:
    return Order.model_validate(order_payload).line_items


def shipbob_line(name: str, sku: str | None, quantity: int, unit_price: str) -> OrderLineItem:
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


def receipt_line(
    description: str,
    amount: str,
    *,
    sku: str | None = None,
    quantity: int | None = None,
) -> ReceiptLine:
    return ReceiptLine(description=description, sku=sku, quantity=quantity, amount=Decimal(amount))


def kinds_of(result: PriceReconciliation) -> list[LineMatchKind]:
    return [line.kind for line in result.lines]


def test_case_1001_two_priced_lines_in_dollars_against_one_line_in_pounds() -> None:
    result = reconcile_prices(
        shipbob_lines_of(ORDER_1001),
        [receipt_line("Item on the merchant's order screenshot", "55.95")],
        policy=Policy(),
        receipt_currency="GBP",
    )

    assert result.shipbob_total == Decimal("90.00")
    assert result.receipt_total == Decimal("55.95")
    assert result.total_difference == Decimal("34.05")
    assert result.totals_diverge is True
    assert result.line_counts_differ is True
    assert (result.shipbob_line_count, result.receipt_line_count) == (2, 1)
    assert kinds_of(result) == [
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.RECEIPT_ONLY,
    ]

    assert result.same_currency is None
    assert result.receipt_currency == "GBP"
    assert "a person chooses" in result.summary


def test_case_1002_three_lines_on_each_side_with_one_product_code_in_common() -> None:
    result = reconcile_prices(
        shipbob_lines_of(ORDER_1002),
        [
            receipt_line("A00299-LV-8-N", "9.95", sku="A00299-LV-8-N", quantity=1),
            receipt_line("A00384-KIT", "16.99", sku="A00384-KIT", quantity=1),
            receipt_line("A00360", "19.99", sku="A00360", quantity=1),
        ],
        policy=Policy(),
        receipt_total=Decimal("49.42"),
    )

    assert result.shipbob_total == Decimal("65.96")
    assert result.receipt_total == Decimal("49.42")
    assert result.line_counts_differ is False

    shared = result.lines[0]
    assert shared.kind is LineMatchKind.MATCHED_ON_SKU
    assert shared.sku == "A00360"
    assert (shared.shipbob_amount, shared.receipt_amount) == (Decimal("24.99"), Decimal("19.99"))
    assert shared.difference == Decimal("5.00")
    assert shared.difference_fraction == Decimal("0.2001")
    assert shared.diverges is True

    assert kinds_of(result)[1:] == [
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.RECEIPT_ONLY,
        LineMatchKind.RECEIPT_ONLY,
    ]


def test_case_1003_shipbob_prices_the_order_at_195_94_after_the_customer_paid_134_99() -> None:
    result = reconcile_prices(
        shipbob_lines_of(ORDER_1003),
        [],
        policy=Policy(),
        receipt_total=Decimal("134.99"),
    )

    assert result.shipbob_total == Decimal("195.94")
    assert result.receipt_total == Decimal("134.99")
    assert result.receipt_total_is_stated is True
    assert result.total_difference == Decimal("60.95")
    assert result.total_difference_fraction == Decimal("0.3111")
    assert result.totals_diverge is True
    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY] * 6
    assert result.has_findings is True


def test_case_1004_one_line_in_shipbob_against_goods_shipping_and_tax_on_the_receipt() -> None:
    result = reconcile_prices(
        shipbob_lines_of(ORDER_1004),
        [
            receipt_line("Organic Castor Oil Roll-on with Frankincense", "51.98", quantity=2),
            receipt_line("Shipping", "6.29"),
            receipt_line("Tax", "3.85"),
        ],
        policy=Policy(),
        receipt_total=Decimal("62.12"),
    )

    item = result.lines[0]
    assert item.kind is LineMatchKind.MATCHED_ON_NAME
    assert (item.shipbob_quantity, item.receipt_quantity) == (1, 2)
    assert (item.shipbob_amount, item.receipt_amount) == (Decimal("24.99"), Decimal("51.98"))
    assert item.difference == Decimal("26.99")
    assert item.diverges is True

    assert kinds_of(result)[1:] == [LineMatchKind.RECEIPT_ONLY, LineMatchKind.RECEIPT_ONLY]
    assert result.receipt_lines_total == Decimal("62.12")
    assert result.total_difference == Decimal("37.13")
    assert result.line_counts_differ is True


def test_two_documents_that_agree_exactly_have_nothing_to_report() -> None:
    shipbob = [
        shipbob_line("Liposomal Tripeptide Collagen", "COLLAGEN1", 1, "52.00"),
        shipbob_line("Additional Collagen Ampoule Duo", "AMP1", 1, "38.00"),
    ]

    result = reconcile_prices(
        shipbob,
        [
            receipt_line("Liposomal Tripeptide Collagen", "52.00", sku="COLLAGEN1", quantity=1),
            receipt_line("Additional Collagen Ampoule Duo", "38.00", sku="AMP1", quantity=1),
        ],
        policy=Policy(),
        shipbob_currency="USD",
        receipt_currency="USD",
    )

    assert kinds_of(result) == [LineMatchKind.MATCHED_ON_SKU, LineMatchKind.MATCHED_ON_SKU]
    assert result.total_difference == Decimal("0.00")
    assert result.totals_diverge is False
    assert result.line_counts_differ is False
    assert result.same_currency is True
    assert result.has_findings is False
    assert "nothing to choose between" in result.summary


def one_line_apart(shipbob_price: str, receipt_price: str, policy: Policy) -> PriceReconciliation:
    return reconcile_prices(
        [shipbob_line("Liposomal Tripeptide Collagen", "COLLAGEN1", 1, shipbob_price)],
        [receipt_line("Liposomal Tripeptide Collagen", receipt_price, sku="COLLAGEN1")],
        policy=policy,
    )


def test_a_gap_just_under_the_threshold_is_not_worth_telling_a_rep_about() -> None:
    result = one_line_apart("100.00", "109.99", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.0999")
    assert result.lines[0].diverges is False
    assert result.totals_diverge is False


def test_a_gap_exactly_on_the_threshold_is_still_allowed() -> None:
    result = one_line_apart("100.00", "110.00", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.1000")
    assert result.lines[0].diverges is False


def test_a_gap_just_over_the_threshold_is_flagged() -> None:
    result = one_line_apart("100.00", "110.01", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.1001")
    assert result.lines[0].diverges is True
    assert result.totals_diverge is True


def test_fr_0_7_the_threshold_comes_from_the_claim_policy_and_not_from_the_code() -> None:
    forgiving = one_line_apart("100.00", "105.00", Policy())
    strict = one_line_apart("100.00", "105.00", Policy(price_divergence_fraction=Decimal("0.01")))

    assert forgiving.lines[0].diverges is False
    assert strict.lines[0].diverges is True
    assert strict.divergence_threshold_fraction == Decimal("0.01")


def test_a_product_code_on_the_receipt_that_matches_nothing_in_shipbobs_records() -> None:
    result = reconcile_prices(
        [shipbob_line("CleanBoss Foaming Cleaning Wipes 70 pack", "A00299", 1, "14.99")],
        [receipt_line("Wipes", "9.95", sku="A00299-LV-8-N")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]
    assert result.lines[0].difference is None
    assert result.lines[1].difference is None


def test_a_line_is_matched_on_its_name_when_neither_side_shows_a_product_code() -> None:
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("Blue Razz Liquid Carnitine", "29.99")],
        policy=Policy(),
    )

    assert result.lines[0].kind is LineMatchKind.MATCHED_ON_NAME
    assert result.lines[0].difference == Decimal("5.00")


def test_capitals_and_extra_spaces_in_a_name_are_typing_and_not_meaning() -> None:
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("  blue   RAZZ liquid Carnitine ", "34.99")],
        policy=Policy(),
    )

    assert result.lines[0].kind is LineMatchKind.MATCHED_ON_NAME
    assert result.has_findings is False


def test_a_name_that_merely_starts_the_same_is_not_a_match() -> None:
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("Blue Razz", "12.99")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]


def test_two_blank_descriptions_are_never_treated_as_the_same_product() -> None:
    result = reconcile_prices(
        [shipbob_line(" ", None, 1, "34.99")],
        [receipt_line("", "29.99")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]


def test_fr_1_13_a_receipt_line_matching_two_shipbob_lines_is_never_narrowed_to_one() -> None:
    result = reconcile_prices(
        [
            shipbob_line("CleanBoss Multi Surface Cleaner 24oz", "A00300", 1, "12.99"),
            shipbob_line("CleanBoss Multi Surface Cleaner 24oz", "A00301", 1, "24.99"),
        ],
        [receipt_line("CleanBoss Multi Surface Cleaner 24oz", "19.99")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.AMBIGUOUS] * 3
    assert all(line.difference is None for line in result.lines)
    assert result.lines[2].ambiguous_with == (
        "CleanBoss Multi Surface Cleaner 24oz",
        "CleanBoss Multi Surface Cleaner 24oz",
    )
    assert "nothing was chosen between" in result.summary


def test_fr_1_13_a_product_code_is_trusted_over_a_name_two_lines_share() -> None:
    result = reconcile_prices(
        [
            shipbob_line("CleanBoss Multi Surface Cleaner 24oz", "A00300", 1, "12.99"),
            shipbob_line("CleanBoss Multi Surface Cleaner 24oz", "A00301", 1, "24.99"),
        ],
        [receipt_line("CleanBoss Multi Surface Cleaner 24oz", "12.99", sku="A00300")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.MATCHED_ON_SKU, LineMatchKind.SHIPBOB_ONLY]
    assert result.lines[0].diverges is False


def test_nfr_4_a_receipt_with_no_lines_is_an_answer_rather_than_a_failure() -> None:
    result = reconcile_prices(shipbob_lines_of(ORDER_1001), [], policy=Policy())

    assert result.shipbob_total == Decimal("90.00")
    assert result.receipt_total == Decimal("0.00")
    assert result.receipt_total_is_stated is False
    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.SHIPBOB_ONLY]
    assert result.line_counts_differ is True


def test_nfr_4_shipbob_records_with_no_lines_leave_every_receipt_line_unmatched() -> None:
    result = reconcile_prices(
        [],
        [receipt_line("Blue Razz Liquid Carnitine", "34.99"), receipt_line("Shipping", "5.00")],
        policy=Policy(),
    )

    assert result.shipbob_total == Decimal("0.00")
    assert result.receipt_total == Decimal("39.99")
    assert kinds_of(result) == [LineMatchKind.RECEIPT_ONLY, LineMatchKind.RECEIPT_ONLY]

    assert result.total_difference_fraction is None
    assert result.totals_diverge is True


def test_two_empty_documents_report_nothing_and_still_answer() -> None:
    result = reconcile_prices([], [], policy=Policy())

    assert result.lines == ()
    assert result.total_difference == Decimal("0.00")
    assert result.totals_diverge is False
    assert result.has_findings is False


def test_a_line_shipbob_prices_at_nothing_against_a_charge_on_the_receipt_diverges() -> None:
    result = reconcile_prices(
        [shipbob_line("Insert Card", "INSERT", 1, "0.00")],
        [receipt_line("Insert Card", "1.50", sku="INSERT")],
        policy=Policy(),
    )

    assert result.lines[0].difference == Decimal("1.50")
    assert result.lines[0].difference_fraction is None
    assert result.lines[0].diverges is True


def test_a_receipt_total_printed_after_a_discount_is_used_ahead_of_its_own_lines() -> None:
    result = reconcile_prices(
        [shipbob_line("Bomb Popsicle Wrecked Pre-Workout", "0041", 1, "195.94")],
        [receipt_line("Bomb Popsicle Wrecked Pre-Workout", "149.98", quantity=3)],
        policy=Policy(),
        receipt_total=Decimal("134.99"),
    )

    assert result.receipt_lines_total == Decimal("149.98")
    assert result.receipt_total == Decimal("134.99")
    assert result.receipt_total_is_stated is True

    assert result.total_difference == Decimal("60.95")


def test_a_currency_label_is_carried_through_and_never_converted() -> None:
    result = reconcile_prices(
        [shipbob_line("Liposomal Tripeptide Collagen", "COLLAGEN1", 1, "52.00")],
        [receipt_line("Liposomal Tripeptide Collagen", "55.95", sku="COLLAGEN1")],
        policy=Policy(),
        shipbob_currency="USD",
        receipt_currency="GBP",
    )

    assert result.shipbob_currency == "USD"
    assert result.receipt_currency == "GBP"
    assert result.same_currency is False
    assert result.lines[0].shipbob_amount == Decimal("52.00")
    assert result.lines[0].receipt_amount == Decimal("55.95")
    assert result.lines[0].diverges is False
    assert "not in the same money" in result.summary


def test_a_currency_label_is_compared_ignoring_capitals_and_spaces() -> None:
    result = reconcile_prices(
        [shipbob_line("Insert Card", "INSERT", 1, "1.00")],
        [receipt_line("Insert Card", "1.00", sku="INSERT")],
        policy=Policy(),
        shipbob_currency="USD",
        receipt_currency=" usd ",
    )

    assert result.same_currency is True


def test_every_figure_that_comes_back_is_exact_money_and_never_a_floating_point_number() -> None:
    result = reconcile_prices(
        [shipbob_line("Insert Card", "INSERT", 3, "0.10")],
        [receipt_line("Insert Card", "0.30", sku="INSERT")],
        policy=Policy(),
    )

    assert result.shipbob_total == Decimal("0.30")
    assert isinstance(result.shipbob_total, Decimal)
    assert isinstance(result.receipt_total, Decimal)
    assert isinstance(result.total_difference, Decimal)
    assert result.lines[0].difference == Decimal("0.00")


def test_nfr_1_the_same_two_documents_compared_twice_come_out_the_same() -> None:
    receipt = [
        receipt_line("A00360", "19.99", sku="A00360"),
        receipt_line("Shipping", "5.00"),
    ]

    first = reconcile_prices(shipbob_lines_of(ORDER_1002), receipt, policy=Policy())
    second = reconcile_prices(shipbob_lines_of(ORDER_1002), receipt, policy=Policy())

    assert first == second
    assert first.summary == second.summary
