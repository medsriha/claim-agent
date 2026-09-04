"""How much a damaged claim line is worth, worked out by code and never by a model.

Every test here builds an invoice and a list of damaged products by hand and calls
one function. Nothing reaches the network, no model is involved, and no clock is
read — which is the point of the rule being written as code in the first place
(FR-1.21).

The invoice used almost everywhere is the one REQUIREMENTS.md quotes in full for
`POST /invoices/generate`: two items, $38.00 and $52.00. The $0.00 promotional
insert card comes from CASE-1005's real order. Anything else is constructed, and
says so, because the sample data cannot reach the cap on a single item — the
largest line across all five cases is $59.99.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.models import Invoice, OrderLineItem
from claim_agent.domain.reimbursement import compute_reimbursement
from claim_agent.policy import Policy

AMPOULE = "Additional Collagen Ampoule Duo"
COLLAGEN = "Liposomal Tripeptide Collagen"


def refunding_the_whole_price(**overrides: object) -> Policy:
    """A policy that refunds all of an item's price, so a test's arithmetic is plain.

    Most of this file is about *which* invoice line an item was matched to and *whether*
    it could be priced at all. Working every expected figure out as a share of the price
    would put arithmetic between the test and the thing it is checking, so the share is
    set aside here and tested on its own further down.
    """
    return Policy(uninsured_refund_percentage=100, **overrides)  # type: ignore[arg-type]


def invoice_line(name: str, sku: str | None, quantity: int, unit_price: str) -> OrderLineItem:
    """One line on an invoice, with its price written as text so it stays exact."""
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


def invoice_of(*lines: OrderLineItem, invoice_id: str = "INV-342578703") -> Invoice:
    """An invoice holding exactly the lines a test cares about."""
    return Invoice(
        invoice_id=invoice_id,
        shipment_id="342578703",
        line_items=lines,
        generated_at=datetime(2026, 3, 21, 10, 0, tzinfo=UTC),
    )


def quoted_invoice() -> Invoice:
    """The invoice REQUIREMENTS.md quotes for CASE-1001's shipment: $38.00 and $52.00."""
    return invoice_of(
        invoice_line(AMPOULE, "AMP1", 1, "38.00"),
        invoice_line(COLLAGEN, "COLLAGEN1", 1, "52.00"),
    )


def damaged(name: str, quantity: int = 1, sku: str | None = None) -> ClaimedProduct:
    """One product an investigation says was damaged."""
    return ClaimedProduct(name=name, quantity=quantity, sku=sku)


# ---------------------------------------------------------------------------
# Where the price comes from (FR-1.18)
# ---------------------------------------------------------------------------


def test_fr_1_18_an_item_is_priced_from_the_invoice_line_carrying_its_product_code() -> None:
    """The code is exact, so it decides the price before the name is even looked at."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN, sku="COLLAGEN1")],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.amount_usd == Decimal("52.00")
    assert amount.priced_from == "INV-342578703"
    assert amount.is_payable
    assert not amount.cap_applied


def test_fr_1_18_an_item_with_no_product_code_is_matched_on_its_name() -> None:
    """A photograph of a broken bottle rarely shows a code, so the name has to do."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )

    assert amount.amount_usd == Decimal("52.00")


def test_fr_1_18_capitals_and_extra_spaces_in_a_name_are_typing_and_not_meaning() -> None:
    """The same product written untidily must still price the same (NFR-1)."""
    amount = compute_reimbursement(
        [damaged("  liposomal   TRIPEPTIDE   collagen ")],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.amount_usd == Decimal("52.00")


def test_fr_1_18_the_product_code_wins_when_the_code_and_the_name_point_at_different_lines() -> (
    None
):
    """A merchant whose code matches one line and whose wording matches another meant the code."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN, sku="AMP1")],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.amount_usd == Decimal("38.00")
    assert amount.components[0].product_name == AMPOULE


def test_fr_1_18_a_name_that_merely_starts_the_same_is_not_a_match() -> None:
    """A looser rule here would quietly pay out on the wrong product."""
    amount = compute_reimbursement(
        [damaged("Liposomal")], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )

    assert amount.components == ()
    assert not amount.is_payable


def test_fr_2_4_a_priced_item_carries_the_invoices_own_name_code_and_price() -> None:
    """The invoice is the document of record, and a payout has to name what it names."""
    amount = compute_reimbursement(
        [damaged("liposomal tripeptide collagen", quantity=1)],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    component = amount.components[0]
    assert component.product_name == COLLAGEN
    assert component.sku == "COLLAGEN1"
    assert component.unit_price == Decimal("52.00")
    assert component.quantity == 1


# ---------------------------------------------------------------------------
# Only the damaged items, and only as many as were invoiced (FR-1.19)
# ---------------------------------------------------------------------------


def test_fr_1_19_only_the_damaged_item_is_covered_and_never_the_whole_order() -> None:
    """The invoice comes to $90.00; one damaged item reimburses $52.00 of it."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )

    assert len(amount.components) == 1
    assert amount.subtotal_usd == Decimal("52.00")


def test_fr_1_19_two_damaged_items_are_priced_line_by_line_and_added_up() -> None:
    """Every item is kept separately so a rep can disagree with one of them (FR-2.4)."""
    amount = compute_reimbursement(
        [damaged(AMPOULE), damaged(COLLAGEN)],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert [component.unit_price for component in amount.components] == [
        Decimal("38.00"),
        Decimal("52.00"),
    ]
    assert amount.amount_usd == Decimal("90.00")


def test_fr_1_19_a_quantity_higher_than_the_invoice_shows_is_reduced_to_what_was_invoiced() -> None:
    """Two bottles were shipped, five are claimed; two is the most that can be paid for."""
    invoice = invoice_of(invoice_line("CleanBoss Multi Surface Cleaner 24oz", "A00300", 2, "12.99"))

    amount = compute_reimbursement(
        [damaged("CleanBoss Multi Surface Cleaner 24oz", quantity=5)],
        invoice=invoice,
        policy=refunding_the_whole_price(),
    )

    assert amount.components[0].quantity == 2
    assert amount.amount_usd == Decimal("25.98")


def test_fr_1_19_a_quantity_below_nothing_can_never_subtract_from_another_items_total() -> None:
    """Nonsense data must lower a figure at worst, never quietly discount a real item."""
    amount = compute_reimbursement(
        [damaged(AMPOULE, quantity=-3), damaged(COLLAGEN)],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.components[0].quantity == 0
    assert amount.amount_usd == Decimal("52.00")


def test_fr_1_19_the_same_invoice_line_claimed_twice_is_not_priced_twice() -> None:
    """One invoiced bottle cannot become two payments because it was listed twice."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN), damaged(COLLAGEN)],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.components == ()
    assert amount.amount_usd == Decimal("0.00")
    assert not amount.is_payable


# ---------------------------------------------------------------------------
# The cap (FR-1.20)
# ---------------------------------------------------------------------------


def test_fr_1_20_a_subtotal_over_the_cap_is_trimmed_to_it_and_says_so() -> None:
    """CASE-1003's two most expensive items come to $109.98, the only sample over the cap."""
    invoice = invoice_of(
        invoice_line("2.5LBS White Chocolate Raspberry Huge Whey", "0159", 1, "59.99"),
        invoice_line("Bomb Popsicle Wrecked Pre-Workout", "0041", 1, "49.99"),
    )

    amount = compute_reimbursement(
        [
            damaged("2.5LBS White Chocolate Raspberry Huge Whey"),
            damaged("Bomb Popsicle Wrecked Pre-Workout"),
        ],
        invoice=invoice,
        policy=refunding_the_whole_price(),
    )

    assert amount.subtotal_usd == Decimal("109.98")
    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied


def test_fr_1_20_a_subtotal_landing_exactly_on_the_cap_is_paid_in_full_and_not_marked_capped() -> (
    None
):
    """Constructed: the cap has changed nothing, so saying it applied would mislead a rep."""
    invoice = invoice_of(invoice_line("Constructed item at the cap", "9001", 1, "100.00"))

    amount = compute_reimbursement(
        [damaged("Constructed item at the cap")],
        invoice=invoice,
        policy=refunding_the_whole_price(),
    )

    assert amount.subtotal_usd == Decimal("100.00")
    assert amount.amount_usd == Decimal("100.00")
    assert not amount.cap_applied


def test_fr_1_20_the_cap_comes_from_the_claim_policy_and_not_from_the_code() -> None:
    """The one policy value ShipBob actually stated is still a configured value (NFR-7)."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)],
        invoice=quoted_invoice(),
        policy=Policy(reimbursement_cap_usd=Decimal("25.00")),
    )

    assert amount.cap_usd == Decimal("25.00")
    assert amount.amount_usd == Decimal("25.00")
    assert amount.cap_applied


def test_fr_1_20_the_cap_is_reported_to_the_cent_however_it_was_configured() -> None:
    """A cap set as "100" and a cap set as "100.00" must read the same on a report."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)],
        invoice=quoted_invoice(),
        policy=Policy(reimbursement_cap_usd=Decimal("100")),
    )

    assert str(amount.cap_usd) == "100.00"


# ---------------------------------------------------------------------------
# Everything that cannot be priced (FR-1.13, FR-1.18)
# ---------------------------------------------------------------------------


def test_fr_1_18_no_invoice_means_nothing_is_priced_and_the_missing_invoice_shows() -> None:
    """The order's prices are not a fallback: the invoice is what the rule names."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=None, policy=refunding_the_whole_price()
    )

    assert amount.components == ()
    assert amount.subtotal_usd == Decimal("0.00")
    assert amount.amount_usd == Decimal("0.00")
    assert amount.priced_from is None
    assert not amount.is_payable


def test_fr_1_18_an_item_that_is_not_on_the_invoice_is_never_priced_from_somewhere_else() -> None:
    """The invoice that was read is still named, so a rep can see what was looked at."""
    amount = compute_reimbursement(
        [damaged("A product nobody ordered")],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.components == ()
    assert amount.amount_usd == Decimal("0.00")
    assert amount.priced_from == "INV-342578703"
    assert not amount.is_payable


def test_fr_1_6_one_unpriceable_item_makes_the_whole_amount_unpayable() -> None:
    """Half an answer is not an answer: the system asks rather than paying partially."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN), damaged("A product nobody ordered")],
        invoice=quoted_invoice(),
        policy=refunding_the_whole_price(),
    )

    assert amount.components == ()
    assert amount.subtotal_usd == Decimal("0.00")
    assert amount.amount_usd == Decimal("0.00")
    assert not amount.cap_applied


def test_fr_1_13_an_item_matching_two_invoice_lines_is_never_priced_by_choosing_one() -> None:
    """Two similar products at different prices: choosing would invent the payout."""
    invoice = invoice_of(
        invoice_line(
            "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack", "A00360", 1, "24.99"
        ),
        invoice_line(
            "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack", "A00361", 1, "12.99"
        ),
    )

    amount = compute_reimbursement(
        [damaged("CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack")],
        invoice=invoice,
        policy=refunding_the_whole_price(),
    )

    assert amount.components == ()
    assert not amount.is_payable


def test_fr_1_18_an_invoice_with_no_lines_prices_nothing() -> None:
    """An empty invoice must not error, and must not price anything either."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=invoice_of(), policy=refunding_the_whole_price()
    )

    assert amount.components == ()
    assert not amount.is_payable


def test_fr_1_21_nothing_established_as_damaged_comes_to_nothing() -> None:
    """An empty list is a real answer, and it is never a reason to pay."""
    amount = compute_reimbursement([], invoice=quoted_invoice(), policy=refunding_the_whole_price())

    assert amount.components == ()
    assert amount.amount_usd == Decimal("0.00")
    assert amount.priced_from == "INV-342578703"
    assert not amount.is_payable


def test_fr_1_18_an_item_the_invoice_prices_at_nothing_comes_to_nothing() -> None:
    """CASE-1005 really carries a free insert card, and nobody has said what that means."""
    invoice = invoice_of(
        invoice_line("30-day Pouch LOAM Prebiotic Fiber Formula", "LOAM-30DAY-001", 1, "45.00"),
        invoice_line("Insert Card", "Health Grows Here - Insert", 1, "0.00"),
    )

    amount = compute_reimbursement(
        [damaged("Insert Card")], invoice=invoice, policy=refunding_the_whole_price()
    )

    assert len(amount.components) == 1
    assert amount.components[0].unit_price == Decimal("0.00")
    assert amount.amount_usd == Decimal("0.00")
    assert not amount.is_payable


# ---------------------------------------------------------------------------
# Money is exact, and the same claim always gives the same figure (NFR-1, NFR-2)
# ---------------------------------------------------------------------------


def test_nfr_2_every_figure_is_an_exact_decimal_and_never_a_floating_point_number() -> None:
    """Cents cannot be allowed to drift, so nothing here is ever a float."""
    amount = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )

    for figure in (amount.subtotal_usd, amount.amount_usd, amount.cap_usd):
        assert isinstance(figure, Decimal)
    assert str(amount.amount_usd) == "52.00"


def test_nfr_1_a_price_ending_in_half_a_cent_is_rounded_up_the_way_money_is() -> None:
    """Constructed: Python's own default rounds half to even, which would lose a cent."""
    invoice = invoice_of(invoice_line("Constructed half cent item", "9002", 1, "1.005"))

    amount = compute_reimbursement(
        [damaged("Constructed half cent item")], invoice=invoice, policy=refunding_the_whole_price()
    )

    assert amount.subtotal_usd == Decimal("1.01")


def test_nfr_1_the_same_damaged_items_priced_twice_give_the_same_figure() -> None:
    """The whole reason the amount is code rather than a model's estimate (FR-1.21)."""
    first = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )
    second = compute_reimbursement(
        [damaged(COLLAGEN)], invoice=quoted_invoice(), policy=refunding_the_whole_price()
    )

    assert first == second


# --- The share of an item's price that is refunded (FR-1.19) -----------------


def test_fr_1_19_only_a_share_of_an_items_price_is_refunded() -> None:
    """FR-1.19: ShipBob refunds part of what a damaged item cost, not all of it.

    The share is a policy value, because it is a commercial decision rather than
    arithmetic. Both figures are kept — what the item cost and what is refunded for it —
    so a rep can see the step between them rather than being handed one number (FR-2.4).
    """
    amount = compute_reimbursement(
        [damaged(COLLAGEN, sku="COLLAGEN1")], invoice=quoted_invoice(), policy=Policy()
    )

    assert amount.items_total_usd == Decimal("52.00")
    assert amount.refund_percentage == 60
    assert amount.subtotal_usd == Decimal("31.20")
    assert amount.amount_usd == Decimal("31.20")
    assert amount.components[0].unit_price == Decimal("52.00")
    assert amount.components[0].refunded_usd == Decimal("31.20")


def test_fr_1_19_the_share_is_a_setting_and_not_a_number_in_the_code() -> None:
    """FR-0.7, NFR-7: the share is a commercial judgement, so it has to be changeable."""
    items = [damaged(COLLAGEN, sku="COLLAGEN1")]

    at_half = compute_reimbursement(
        items, invoice=quoted_invoice(), policy=Policy(uninsured_refund_percentage=50)
    )
    at_none = compute_reimbursement(
        items, invoice=quoted_invoice(), policy=Policy(uninsured_refund_percentage=0)
    )

    assert at_half.amount_usd == Decimal("26.00")
    assert at_none.amount_usd == Decimal("0.00")
    # Refunding nothing is not the same as having nothing to refund: the item was still
    # priced, so a rep can see what it cost and why the figure came to zero.
    assert at_none.items_total_usd == Decimal("52.00")
    assert at_none.is_payable is False


def test_fr_1_21_a_share_that_does_not_divide_evenly_is_rounded_to_cents() -> None:
    """FR-1.21, FR-0.6: money stays exact, and the same item always comes to the figure.

    60% of $49.99 is $29.994, which is not an amount of money. It is rounded half up,
    the way money is normally rounded, in exact decimals — never through a floating point
    number, where the value could not be held exactly in the first place.
    """
    invoice = Invoice(
        invoice_id="INV-337761802",
        line_items=(
            OrderLineItem(
                name="Bomb Popsicle Wrecked Pre-Workout",
                sku="0041",
                quantity=1,
                unit_price=Decimal("49.99"),
            ),
        ),
    )

    amount = compute_reimbursement(
        [damaged("Bomb Popsicle Wrecked Pre-Workout", sku="0041")],
        invoice=invoice,
        policy=Policy(),
    )

    assert amount.amount_usd == Decimal("29.99")
    assert isinstance(amount.amount_usd, Decimal)


def test_fr_1_19_the_lines_a_rep_reads_add_up_to_the_total_beside_them() -> None:
    """FR-2.4: a working that does not add up is worse than no working.

    Each item's share is rounded to cents before the items are added together, so the
    figures on the page add up. Rounding the total instead would leave a rep checking
    the arithmetic and finding it wrong by a penny.
    """
    amount = compute_reimbursement(
        [damaged(AMPOULE, sku="AMP1"), damaged(COLLAGEN, sku="COLLAGEN1")],
        invoice=quoted_invoice(),
        policy=Policy(),
    )

    assert [component.refunded_usd for component in amount.components] == [
        Decimal("22.80"),
        Decimal("31.20"),
    ]
    assert amount.subtotal_usd == sum(component.refunded_usd for component in amount.components)
    assert amount.subtotal_usd == Decimal("54.00")


def test_fr_1_20_the_cap_is_checked_against_the_refunded_share_not_the_price() -> None:
    """FR-1.20: the cap limits what is paid, so it is applied after the share is taken.

    An order of goods worth more than the cap does not breach it if the share brings the
    refund back under. Checking the cap against the price instead would trim a figure
    that was never over the limit.
    """
    invoice = Invoice(
        invoice_id="INV-337761802",
        line_items=(
            OrderLineItem(
                name="2.5LBS White Chocolate Raspberry Huge Whey",
                sku="0159",
                quantity=3,
                unit_price=Decimal("59.99"),
            ),
        ),
    )
    items = [damaged("2.5LBS White Chocolate Raspberry Huge Whey", sku="0159", quantity=3)]

    amount = compute_reimbursement(items, invoice=invoice, policy=Policy())

    # $179.97 of goods, well over the $100 cap; $107.98 refundable, still over it.
    assert amount.items_total_usd == Decimal("179.97")
    assert amount.subtotal_usd == Decimal("107.98")
    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied is True

    # At a smaller share the same goods no longer reach the cap at all.
    modest = compute_reimbursement(
        items, invoice=invoice, policy=Policy(uninsured_refund_percentage=40)
    )
    assert modest.items_total_usd == Decimal("179.97")
    assert modest.amount_usd == Decimal("71.99")
    assert modest.cap_applied is False
