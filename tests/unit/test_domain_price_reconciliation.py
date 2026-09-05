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
    """The priced lines ShipBob holds for one of the sample orders."""
    return Order.model_validate(order_payload).line_items


def shipbob_line(name: str, sku: str | None, quantity: int, unit_price: str) -> OrderLineItem:
    """One line in ShipBob's records, with its price written as text so it stays exact."""
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


def receipt_line(
    description: str,
    amount: str,
    *,
    sku: str | None = None,
    quantity: int | None = None,
) -> ReceiptLine:
    """One line as it is printed on the customer's receipt, its figure read as text."""
    return ReceiptLine(description=description, sku=sku, quantity=quantity, amount=Decimal(amount))


def kinds_of(result: PriceReconciliation) -> list[LineMatchKind]:
    """How each line of the comparison turned out, in the order it is reported."""
    return [line.kind for line in result.lines]


# ---------------------------------------------------------------------------
# The four sample claims that carry evidence
# ---------------------------------------------------------------------------


def test_case_1001_two_priced_lines_in_dollars_against_one_line_in_pounds() -> None:
    """CASE-1001: ShipBob shows two lines totalling 90.00; the screenshot shows one, £55.95.

    Both figures are real. Which product the screenshot's single line names could not be
    read off the image, so it is given a description that matches neither ShipBob line —
    which is also what makes the two-against-one finding visible.

    The currency is the quiet danger here. ShipBob's records carry no currency field
    anywhere, so 90.00 is a bare number; the screenshot reads in pounds. Nothing converts
    between them, and the summary says the two may not be comparable at all.
    """
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
    # Nobody knows whether these two figures are even in the same money.
    assert result.same_currency is None
    assert result.receipt_currency == "GBP"
    assert "a person chooses" in result.summary


def test_case_1002_three_lines_on_each_side_with_one_product_code_in_common() -> None:
    """CASE-1002: 65.96 in ShipBob's records against a sales order printing $49.42.

    Every figure and every product code below is real. The item wording on the sales order
    was not recorded, so each receipt line is described by the code printed on it.

    This is the case that shows why counting lines is not enough: both documents list three
    lines, so the counts agree, and yet only one product code appears on both. The one
    product they do share is priced 24.99 against 19.99, a fifth apart.
    """
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

    # A code with an extra suffix on the end is a different code, so nothing is tied to it.
    assert kinds_of(result)[1:] == [
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.SHIPBOB_ONLY,
        LineMatchKind.RECEIPT_ONLY,
        LineMatchKind.RECEIPT_ONLY,
    ]


def test_case_1003_shipbob_prices_the_order_at_195_94_after_the_customer_paid_134_99() -> None:
    """CASE-1003: the overpayment this whole comparison exists to catch.

    ShipBob's six lines come to 195.94. The customer's invoice shows a subtotal of 149.98,
    a discount of 14.99, and a total of 134.99 — sixty dollars less. A claim priced off
    ShipBob's figure is priced off a number the customer never paid.

    The invoice's four individual lines were not recorded, only its printed total, so the
    receipt side here is a total and nothing else. That is a real shape for this tool to
    handle: a total is often legible when the lines are not.
    """
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
    """CASE-1004: 24.99 in ShipBob's records against 62.12 on the customer's receipt.

    The receipt charges two of the item at 51.98, then 6.29 shipping and 3.85 tax, coming
    to 62.12. All four figures are real. The receipt's wording for the item itself was not
    recorded; ShipBob's name is used for it here, which is what lets the comparison land on
    one line and show the gap rather than reporting two strangers.

    Two findings sit on top of each other. The item is charged twice over on the receipt and
    once in ShipBob's records, and the receipt carries shipping and tax that ShipBob's
    records know nothing about — which is the ordinary reason a receipt total is larger, and
    not by itself evidence of anything wrong.
    """
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


# ---------------------------------------------------------------------------
# Two documents that agree
# ---------------------------------------------------------------------------


def test_two_documents_that_agree_exactly_have_nothing_to_report() -> None:
    """The quiet case, and the one a representative should be able to skip past.

    Same lines, same codes, same figures, same money. Every line is matched, nothing
    diverges, and the summary says outright that there is nothing to choose between.
    """
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


# ---------------------------------------------------------------------------
# How far apart is too far apart (FR-0.7, NFR-7)
# ---------------------------------------------------------------------------


def one_line_apart(shipbob_price: str, receipt_price: str, policy: Policy) -> PriceReconciliation:
    """Compare two documents holding one line each, priced as asked."""
    return reconcile_prices(
        [shipbob_line("Liposomal Tripeptide Collagen", "COLLAGEN1", 1, shipbob_price)],
        [receipt_line("Liposomal Tripeptide Collagen", receipt_price, sku="COLLAGEN1")],
        policy=policy,
    )


def test_a_gap_just_under_the_threshold_is_not_worth_telling_a_rep_about() -> None:
    """Below the setting, so the line is compared and nothing is flagged.

    Prices drift for ordinary reasons — a promotion, a rounding, a price changed since the
    order — and a comparison that shouted about every one of them would be ignored.
    """
    result = one_line_apart("100.00", "109.99", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.0999")
    assert result.lines[0].diverges is False
    assert result.totals_diverge is False


def test_a_gap_exactly_on_the_threshold_is_still_allowed() -> None:
    """The setting reads as how far apart two prices may sit, so exactly that far is fine.

    Worth pinning down, because a threshold everyone reads two ways is a threshold nobody
    can set with confidence.
    """
    result = one_line_apart("100.00", "110.00", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.1000")
    assert result.lines[0].diverges is False


def test_a_gap_just_over_the_threshold_is_flagged() -> None:
    """One cent past the line, and a representative is told."""
    result = one_line_apart("100.00", "110.01", Policy())

    assert result.lines[0].difference_fraction == Decimal("0.1001")
    assert result.lines[0].diverges is True
    assert result.totals_diverge is True


def test_fr_0_7_the_threshold_comes_from_the_claim_policy_and_not_from_the_code() -> None:
    """FR-0.7, NFR-7: how far apart is too far apart is a judgement, so it is a setting.

    The same two prices are unremarkable under one policy and worth flagging under a
    stricter one, and the threshold that decided it is reported beside the answer so a
    reader can see what "too far apart" meant on this run (NFR-3).
    """
    forgiving = one_line_apart("100.00", "105.00", Policy())
    strict = one_line_apart("100.00", "105.00", Policy(price_divergence_fraction=Decimal("0.01")))

    assert forgiving.lines[0].diverges is False
    assert strict.lines[0].diverges is True
    assert strict.divergence_threshold_fraction == Decimal("0.01")


# ---------------------------------------------------------------------------
# Lines only one of the documents knows about
# ---------------------------------------------------------------------------


def test_a_product_code_on_the_receipt_that_matches_nothing_in_shipbobs_records() -> None:
    """A code that matches nothing is reported as unmatched, never matched loosely.

    CASE-1002's receipt is exactly this: it prints A00299-LV-8-N where ShipBob's records
    hold A00299. A rule that let one stand for the other would compare a $9.95 item against
    a $14.99 one on the strength of a shared prefix, and the prices are how a claim is paid.
    """
    result = reconcile_prices(
        [shipbob_line("CleanBoss Foaming Cleaning Wipes 70 pack", "A00299", 1, "14.99")],
        [receipt_line("Wipes", "9.95", sku="A00299-LV-8-N")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]
    assert result.lines[0].difference is None
    assert result.lines[1].difference is None


def test_a_line_is_matched_on_its_name_when_neither_side_shows_a_product_code() -> None:
    """A photographed receipt often prints no codes at all, only what the thing was called."""
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("Blue Razz Liquid Carnitine", "29.99")],
        policy=Policy(),
    )

    assert result.lines[0].kind is LineMatchKind.MATCHED_ON_NAME
    assert result.lines[0].difference == Decimal("5.00")


def test_capitals_and_extra_spaces_in_a_name_are_typing_and_not_meaning() -> None:
    """Forgiven, because a receipt sets its own capitals and a reader adds its own spaces."""
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("  blue   RAZZ liquid Carnitine ", "34.99")],
        policy=Policy(),
    )

    assert result.lines[0].kind is LineMatchKind.MATCHED_ON_NAME
    assert result.has_findings is False


def test_a_name_that_merely_starts_the_same_is_not_a_match() -> None:
    """FR-1.13: a looser rule would tie a claim to the wrong product and pay out on it."""
    result = reconcile_prices(
        [shipbob_line("Blue Razz Liquid Carnitine", None, 1, "34.99")],
        [receipt_line("Blue Razz", "12.99")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]


def test_two_blank_descriptions_are_never_treated_as_the_same_product() -> None:
    """A line nobody could read a name off matches nothing, rather than matching everything."""
    result = reconcile_prices(
        [shipbob_line(" ", None, 1, "34.99")],
        [receipt_line("", "29.99")],
        policy=Policy(),
    )

    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.RECEIPT_ONLY]


# ---------------------------------------------------------------------------
# Never choosing between two candidates (FR-1.13)
# ---------------------------------------------------------------------------


def test_fr_1_13_a_receipt_line_matching_two_shipbob_lines_is_never_narrowed_to_one() -> None:
    """FR-1.13: two similar products at different prices, and the choice would be the payout.

    CASE-1002 is the real example — two 24oz CleanBoss bottles at 12.99 and 24.99. Faced
    with one receipt line that could be either, the comparison reports all three lines as
    ambiguous, names what each could have been, and compares nothing.
    """
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
    """FR-1.13: a code is exact, so it settles a pairing a shared name would confuse.

    The two ShipBob lines are called the same thing, which alone would be ambiguous. Their
    codes are different and the receipt prints one of them, so that line pairs cleanly and
    the other is simply a line the receipt does not mention.
    """
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


# ---------------------------------------------------------------------------
# Empty documents (NFR-4)
# ---------------------------------------------------------------------------


def test_nfr_4_a_receipt_with_no_lines_is_an_answer_rather_than_a_failure() -> None:
    """NFR-4: nothing is raised, because a representative can act on a finding.

    The comparison says what ShipBob holds, says the receipt yielded nothing, and leaves it
    there. Refusing to answer would hand a rep an error with nothing to do about it.
    """
    result = reconcile_prices(shipbob_lines_of(ORDER_1001), [], policy=Policy())

    assert result.shipbob_total == Decimal("90.00")
    assert result.receipt_total == Decimal("0.00")
    assert result.receipt_total_is_stated is False
    assert kinds_of(result) == [LineMatchKind.SHIPBOB_ONLY, LineMatchKind.SHIPBOB_ONLY]
    assert result.line_counts_differ is True


def test_nfr_4_shipbob_records_with_no_lines_leave_every_receipt_line_unmatched() -> None:
    """NFR-4: the mirror image — an invoice that priced nothing at all.

    Every figure on the receipt is then a charge ShipBob's records cannot account for,
    which is exactly what a representative needs told.
    """
    result = reconcile_prices(
        [],
        [receipt_line("Blue Razz Liquid Carnitine", "34.99"), receipt_line("Shipping", "5.00")],
        policy=Policy(),
    )

    assert result.shipbob_total == Decimal("0.00")
    assert result.receipt_total == Decimal("39.99")
    assert kinds_of(result) == [LineMatchKind.RECEIPT_ONLY, LineMatchKind.RECEIPT_ONLY]
    # Nothing can be a share of nothing, so the gap is reported without one.
    assert result.total_difference_fraction is None
    assert result.totals_diverge is True


def test_two_empty_documents_report_nothing_and_still_answer() -> None:
    """Nothing on either side is a comparison with no findings, not an error."""
    result = reconcile_prices([], [], policy=Policy())

    assert result.lines == ()
    assert result.total_difference == Decimal("0.00")
    assert result.totals_diverge is False
    assert result.has_findings is False


def test_a_line_shipbob_prices_at_nothing_against_a_charge_on_the_receipt_diverges() -> None:
    """Any gap from nothing is a complete one, however small the figure.

    CASE-1005 carries a free promotional insert. A receipt charging for one is a
    disagreement worth reporting, even though the gap cannot be written as a share.
    """
    result = reconcile_prices(
        [shipbob_line("Insert Card", "INSERT", 1, "0.00")],
        [receipt_line("Insert Card", "1.50", sku="INSERT")],
        policy=Policy(),
    )

    assert result.lines[0].difference == Decimal("1.50")
    assert result.lines[0].difference_fraction is None
    assert result.lines[0].diverges is True


# ---------------------------------------------------------------------------
# Money, currency and repeatability
# ---------------------------------------------------------------------------


def test_a_receipt_total_printed_after_a_discount_is_used_ahead_of_its_own_lines() -> None:
    """The customer paid the printed total, not the sum of the lines above it.

    CASE-1003's invoice is this shape: item lines coming to 149.98, then a discount of
    14.99 struck off below them, then a total of 134.99. Its lines do not add up to its own
    total, and that is normal rather than broken. Both figures are reported, and the printed
    one is the one compared, because that is the money that changed hands.
    """
    result = reconcile_prices(
        [shipbob_line("Bomb Popsicle Wrecked Pre-Workout", "0041", 1, "195.94")],
        [receipt_line("Bomb Popsicle Wrecked Pre-Workout", "149.98", quantity=3)],
        policy=Policy(),
        receipt_total=Decimal("134.99"),
    )

    assert result.receipt_lines_total == Decimal("149.98")
    assert result.receipt_total == Decimal("134.99")
    assert result.receipt_total_is_stated is True
    # The gap is measured against what the customer paid, not against the lines above it.
    assert result.total_difference == Decimal("60.95")


def test_a_currency_label_is_carried_through_and_never_converted() -> None:
    """Pounds against dollars is reported as it stands, with no rate applied to either.

    The two figures are 55.95 and 52.00. As bare numbers they are under eight percent
    apart, which does not even reach the threshold — so the price flag stays quiet while
    the real gap, pounds against dollars, is the whole story. Converting here would hide it
    behind a rate nobody signed off; saying the two are not in the same money puts it in
    front of a representative and leaves the decision with them.
    """
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
    """Two documents both saying dollars agree, however each of them wrote it down."""
    result = reconcile_prices(
        [shipbob_line("Insert Card", "INSERT", 1, "1.00")],
        [receipt_line("Insert Card", "1.00", sku="INSERT")],
        policy=Policy(),
        shipbob_currency="USD",
        receipt_currency=" usd ",
    )

    assert result.same_currency is True


def test_every_figure_that_comes_back_is_exact_money_and_never_a_floating_point_number() -> None:
    """Money read as text into an exact decimal, so cents cannot drift (FR-1.21).

    0.10 is the one that matters: it cannot be held exactly as a binary floating point
    number at all, so a figure that went through one would have drifted before anybody read
    it.
    """
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
    """NFR-1: no clock, no randomness, and nothing that depends on ordering.

    A comparison a representative cannot reproduce is one they cannot check, and this one
    feeds a figure that eventually pays a merchant.
    """
    receipt = [
        receipt_line("A00360", "19.99", sku="A00360"),
        receipt_line("Shipping", "5.00"),
    ]

    first = reconcile_prices(shipbob_lines_of(ORDER_1002), receipt, policy=Policy())
    second = reconcile_prices(shipbob_lines_of(ORDER_1002), receipt, policy=Policy())

    assert first == second
    assert first.summary == second.summary
