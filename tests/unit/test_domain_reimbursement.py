from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.models import Invoice, OrderLineItem
from claim_agent.domain.reimbursement import AmountDerivation, review_recommended_amount
from claim_agent.policy import Policy

AMPOULE = "Additional Collagen Ampoule Duo"
COLLAGEN = "Liposomal Tripeptide Collagen"


def invoice_line(name: str, sku: str | None, quantity: int, unit_price: str) -> OrderLineItem:
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


def invoice_of(*lines: OrderLineItem, invoice_id: str = "INV-342578703") -> Invoice:
    return Invoice(
        invoice_id=invoice_id,
        shipment_id="342578703",
        line_items=lines,
        generated_at=datetime(2026, 3, 21, 10, 0, tzinfo=UTC),
    )


def quoted_invoice() -> Invoice:
    return invoice_of(
        invoice_line(AMPOULE, "AMP1", 1, "38.00"),
        invoice_line(COLLAGEN, "COLLAGEN1", 1, "52.00"),
    )


def damaged(name: str, quantity: int = 1, sku: str | None = None) -> ClaimedProduct:
    return ClaimedProduct(name=name, quantity=quantity, sku=sku)


UNSPECIFIED = object()


def reviewed(
    proposed: str,
    *,
    items: list[ClaimedProduct] | None = None,
    invoice: Invoice | object | None = UNSPECIFIED,
    policy: Policy | None = None,
    reasoning: str = "The bottle is smashed and leaking.",
) -> AmountDerivation:
    return review_recommended_amount(
        proposed,
        reasoning=reasoning,
        damaged=items if items is not None else [damaged(COLLAGEN, sku="COLLAGEN1")],
        invoice=quoted_invoice() if invoice is UNSPECIFIED else cast("Invoice | None", invoice),
        policy=policy if policy is not None else Policy(),
    )


def test_fr_1_21_the_figure_the_investigation_named_is_what_is_recommended() -> None:
    amount = reviewed("40.00")

    assert amount.proposed_usd == Decimal("40.00")
    assert amount.amount_usd == Decimal("40.00")
    assert amount.cap_applied is False

    assert amount.items_total_usd == Decimal("52.00")


def test_fr_1_21_a_claim_may_be_worth_more_or_less_than_the_goods_cost() -> None:
    modest = reviewed("10.00")
    generous = reviewed("80.00")

    assert modest.amount_usd == Decimal("10.00")
    assert generous.amount_usd == Decimal("80.00")
    assert generous.items_total_usd == Decimal("52.00")
    assert generous.cap_applied is False


def test_nfr_3_the_reasoning_for_a_figure_travels_with_it() -> None:
    amount = reviewed("40.00", reasoning="Both ampoules leaked over the box.")

    assert amount.reasoning == "Both ampoules leaked over the box."


def test_fr_1_20_a_figure_over_the_cap_is_brought_down_to_it_and_says_so() -> None:
    amount = reviewed("250.00")

    assert amount.proposed_usd == Decimal("250.00")
    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied is True
    assert amount.cap_usd == Decimal("100.00")


def test_fr_1_20_a_figure_landing_exactly_on_the_cap_is_paid_in_full() -> None:
    amount = reviewed("100.00")

    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied is False


def test_fr_0_7_the_cap_comes_from_the_claim_policy_and_not_from_the_code() -> None:
    amount = reviewed("60.00", policy=Policy(reimbursement_cap_usd=Decimal("25.00")))

    assert amount.cap_usd == Decimal("25.00")
    assert amount.amount_usd == Decimal("25.00")
    assert amount.cap_applied is True


def test_fr_1_20_a_cap_of_nothing_pays_nothing() -> None:
    amount = reviewed("40.00", policy=Policy(reimbursement_cap_usd=Decimal("0.00")))

    assert amount.amount_usd == Decimal("0.00")
    assert amount.is_payable is False


@pytest.mark.parametrize("written", ["40", "40.0", "40.00", "0", "0.10", "99.99"])
def test_fr_1_21_a_figure_written_as_money_is_read_exactly(written: str) -> None:
    amount = reviewed(written)

    assert amount.proposed_usd == Decimal(written)
    assert isinstance(amount.proposed_usd, Decimal)
    assert isinstance(amount.amount_usd, Decimal)


@pytest.mark.parametrize(
    "written",
    ["$40", "40 dollars", "forty", "-5", "1,000", "40.005", "4e2", "", "  ", "40.00.00"],
)
def test_fr_1_21_anything_that_is_not_money_is_refused_and_never_interpreted(
    written: str,
) -> None:
    with pytest.raises(ValueError, match="written as money"):
        reviewed(written)


def test_fr_1_21_a_third_decimal_place_is_refused_rather_than_rounded() -> None:
    with pytest.raises(ValueError, match="written as money"):
        reviewed("40.005")


def test_a_figure_with_spaces_around_it_is_still_money() -> None:
    assert reviewed("  40.00  ").amount_usd == Decimal("40.00")


def test_fr_2_4_an_item_is_matched_to_the_invoice_line_carrying_its_product_code() -> None:
    amount = reviewed("30.00", items=[damaged(COLLAGEN, sku="COLLAGEN1")])

    assert [component.unit_price for component in amount.components] == [Decimal("52.00")]
    assert amount.priced_from == "INV-342578703"


def test_fr_2_4_an_item_with_no_product_code_is_matched_on_its_name() -> None:
    amount = reviewed("30.00", items=[damaged(COLLAGEN)])

    assert [component.product_name for component in amount.components] == [COLLAGEN]


def test_fr_2_4_capitals_and_extra_spaces_in_a_name_are_typing_and_not_meaning() -> None:
    amount = reviewed("30.00", items=[damaged("  liposomal   TRIPEPTIDE collagen ")])

    assert [component.product_name for component in amount.components] == [COLLAGEN]


def test_fr_2_4_a_name_that_merely_starts_the_same_is_not_a_match() -> None:
    amount = reviewed("30.00", items=[damaged("Liposomal")])

    assert amount.components == ()


def test_fr_1_13_an_item_matching_two_invoice_lines_is_never_narrowed_to_one() -> None:
    twice = invoice_of(
        invoice_line("CleanBoss Multi Surface Cleaner 24oz", "A00300", 1, "12.99"),
        invoice_line("CleanBoss Multi Surface Cleaner 24oz", "A00301", 1, "24.99"),
    )

    amount = reviewed(
        "20.00", items=[damaged("CleanBoss Multi Surface Cleaner 24oz")], invoice=twice
    )

    assert amount.components == ()
    assert amount.amount_usd == Decimal("20.00")


def test_fr_2_4_a_quantity_higher_than_the_invoice_shows_is_reduced_to_what_was_invoiced() -> None:
    amount = reviewed(
        "30.00",
        items=[damaged(COLLAGEN, quantity=5, sku="COLLAGEN1")],
        invoice=invoice_of(invoice_line(COLLAGEN, "COLLAGEN1", 2, "52.00")),
    )

    assert [component.quantity for component in amount.components] == [2]
    assert amount.items_total_usd == Decimal("104.00")


def test_fr_1_18_no_invoice_means_no_item_context_and_the_figure_still_stands() -> None:
    amount = reviewed("30.00", invoice=None)

    assert amount.components == ()
    assert amount.items_total_usd == Decimal("0.00")
    assert amount.priced_from is None
    assert amount.amount_usd == Decimal("30.00")


def test_fr_1_18_an_item_that_is_not_on_the_invoice_is_never_priced_from_somewhere_else() -> None:
    amount = reviewed("30.00", items=[damaged("Beef Trachea Chews")])

    assert amount.components == ()
    assert amount.priced_from == "INV-342578703"


def test_an_item_the_invoice_prices_at_nothing_still_shows_as_costing_nothing() -> None:
    free = invoice_of(invoice_line("Insert Card", "INSERT", 1, "0.00"))

    amount = reviewed("5.00", items=[damaged("Insert Card", sku="INSERT")], invoice=free)

    assert amount.items_total_usd == Decimal("0.00")
    assert amount.amount_usd == Decimal("5.00")


def test_a_figure_of_nothing_is_not_payable() -> None:
    amount = reviewed("0")

    assert amount.amount_usd == Decimal("0.00")
    assert amount.is_payable is False


def test_nfr_1_the_same_figure_reviewed_twice_comes_out_the_same() -> None:
    assert reviewed("40.00") == reviewed("40.00")
