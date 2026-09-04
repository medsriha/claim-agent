"""What a claim is recommended for: the investigation's figure, held to the cap.

The investigation decides what the damage is worth. This module does two things to that
figure and nothing else — reads it as exact money, and refuses to let it exceed the
reimbursement cap — so the tests come in two halves.

**The cap.** The only limit on a recommended amount, and the one thing here no
investigation can talk its way past (FR-1.20).

**Reading the figure.** Money arrives as text and is parsed. Anything that is not money is
refused rather than interpreted, because a payout somebody had to guess at is worse than no
payout at all.

The items are still read off the invoice, but only as context now — what the goods cost,
shown beside what is being recommended for them. Those tests are still here because
matching a claimed product to an invoice line is unchanged and still easy to get wrong.

The invoice used almost everywhere is the one REQUIREMENTS.md quotes in full for
`POST /invoices/generate`: two items, $38.00 and $52.00. The $0.00 promotional insert card
comes from CASE-1005's real order.
"""

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


#: Stands for "this test did not say", so that passing `invoice=None` can mean the real
#: thing — a shipment ShipBob would not price — rather than falling back to a default.
UNSPECIFIED = object()


def reviewed(
    proposed: str,
    *,
    items: list[ClaimedProduct] | None = None,
    invoice: Invoice | object | None = UNSPECIFIED,
    policy: Policy | None = None,
    reasoning: str = "The bottle is smashed and leaking.",
) -> AmountDerivation:
    """Put a figure the investigation proposed through the cap."""
    return review_recommended_amount(
        proposed,
        reasoning=reasoning,
        damaged=items if items is not None else [damaged(COLLAGEN, sku="COLLAGEN1")],
        invoice=quoted_invoice() if invoice is UNSPECIFIED else cast("Invoice | None", invoice),
        policy=policy if policy is not None else Policy(),
    )


# ---------------------------------------------------------------------------
# The investigation decides the figure (FR-1.21)
# ---------------------------------------------------------------------------


def test_fr_1_21_the_figure_the_investigation_named_is_what_is_recommended() -> None:
    """FR-1.21: the agent judges what the damage is worth, and nothing recomputes it.

    Deliberately not a share of what the item cost. A smashed bottle and a scuffed box can
    cost the same and be worth very different amounts to put right, which is the judgement
    this reversal exists to allow.
    """
    amount = reviewed("40.00")

    assert amount.proposed_usd == Decimal("40.00")
    assert amount.amount_usd == Decimal("40.00")
    assert amount.cap_applied is False
    # What the item cost is shown beside it, and is not what decided it.
    assert amount.items_total_usd == Decimal("52.00")


def test_fr_1_21_a_claim_may_be_worth_more_or_less_than_the_goods_cost() -> None:
    """FR-1.21: what the item cost is context, and deliberately not a limit.

    Nothing in the requirements says a claim may never exceed the price of the goods, so
    nothing here decides that. Whether it should is a question for whoever owns them, and
    it is written down in DESIGN.md rather than answered by quietly clamping the figure.
    """
    modest = reviewed("10.00")
    generous = reviewed("80.00")

    assert modest.amount_usd == Decimal("10.00")
    assert generous.amount_usd == Decimal("80.00")
    assert generous.items_total_usd == Decimal("52.00")
    assert generous.cap_applied is False


def test_nfr_3_the_reasoning_for_a_figure_travels_with_it() -> None:
    """NFR-3: the amount is a judgement now, so the account of it is the whole review.

    An arithmetic figure could be checked by redoing the sum. This one cannot, so the only
    thing a representative can weigh is why it was chosen.
    """
    amount = reviewed("40.00", reasoning="Both ampoules leaked over the box.")

    assert amount.reasoning == "Both ampoules leaked over the box."


# ---------------------------------------------------------------------------
# The cap is the only limit (FR-1.20)
# ---------------------------------------------------------------------------


def test_fr_1_20_a_figure_over_the_cap_is_brought_down_to_it_and_says_so() -> None:
    """FR-1.20: the cap is the one thing an investigation cannot talk its way past.

    It is also the whole guardrail now that the figure is a judgement, so the result says
    plainly both what was wanted and what will be paid.
    """
    amount = reviewed("250.00")

    assert amount.proposed_usd == Decimal("250.00")
    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied is True
    assert amount.cap_usd == Decimal("100.00")


def test_fr_1_20_a_figure_landing_exactly_on_the_cap_is_paid_in_full() -> None:
    """FR-1.20: the cap changed nothing, so saying it applied would misreport it.

    A rep reading "capped" takes it to mean the figure was trimmed. On the limit it was not.
    """
    amount = reviewed("100.00")

    assert amount.amount_usd == Decimal("100.00")
    assert amount.cap_applied is False


def test_fr_0_7_the_cap_comes_from_the_claim_policy_and_not_from_the_code() -> None:
    """FR-0.7, NFR-7: the one stated ShipBob figure, and still a setting."""
    amount = reviewed("60.00", policy=Policy(reimbursement_cap_usd=Decimal("25.00")))

    assert amount.cap_usd == Decimal("25.00")
    assert amount.amount_usd == Decimal("25.00")
    assert amount.cap_applied is True


def test_fr_1_20_a_cap_of_nothing_pays_nothing() -> None:
    """FR-1.20: a limit of zero is a real configuration, and it holds."""
    amount = reviewed("40.00", policy=Policy(reimbursement_cap_usd=Decimal("0.00")))

    assert amount.amount_usd == Decimal("0.00")
    assert amount.is_payable is False


# ---------------------------------------------------------------------------
# Reading a figure as money (FR-1.21, NFR-2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("written", ["40", "40.0", "40.00", "0", "0.10", "99.99"])
def test_fr_1_21_a_figure_written_as_money_is_read_exactly(written: str) -> None:
    """FR-1.21: text into an exact decimal, never through a floating point number.

    `0.10` is the one that matters: it cannot be held exactly as a binary float at all, so
    a figure that went through one would already have drifted before anything was paid.
    """
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
    """FR-1.21, NFR-4: a payout somebody had to guess at is worse than no payout.

    Each of these is a figure a person would have to interpret — a symbol, a word, a third
    decimal place, a thousands separator. Interpreting one quietly is exactly what must not
    happen, so it is refused and the caller hands the claim to a person.
    """
    with pytest.raises(ValueError, match="written as money"):
        reviewed(written)


def test_fr_1_21_a_third_decimal_place_is_refused_rather_than_rounded() -> None:
    """FR-1.21: rounding it would be this code deciding what was meant.

    $40.005 could be $40.00 or $40.01. Choosing is a payout decision, and it is not one to
    make on a model's behalf without saying so.
    """
    with pytest.raises(ValueError, match="written as money"):
        reviewed("40.005")


def test_a_figure_with_spaces_around_it_is_still_money() -> None:
    """Whitespace is typing rather than meaning, and is the one thing forgiven."""
    assert reviewed("  40.00  ").amount_usd == Decimal("40.00")


# ---------------------------------------------------------------------------
# What the items cost, shown for context (FR-2.4)
# ---------------------------------------------------------------------------


def test_fr_2_4_an_item_is_matched_to_the_invoice_line_carrying_its_product_code() -> None:
    """FR-2.4: a code is exact, so it is tried first."""
    amount = reviewed("30.00", items=[damaged(COLLAGEN, sku="COLLAGEN1")])

    assert [component.unit_price for component in amount.components] == [Decimal("52.00")]
    assert amount.priced_from == "INV-342578703"


def test_fr_2_4_an_item_with_no_product_code_is_matched_on_its_name() -> None:
    """FR-2.4: a photograph of a broken bottle rarely shows a product code."""
    amount = reviewed("30.00", items=[damaged(COLLAGEN)])

    assert [component.product_name for component in amount.components] == [COLLAGEN]


def test_fr_2_4_capitals_and_extra_spaces_in_a_name_are_typing_and_not_meaning() -> None:
    """FR-2.4: ignored, and nothing looser than that is."""
    amount = reviewed("30.00", items=[damaged("  liposomal   TRIPEPTIDE collagen ")])

    assert [component.product_name for component in amount.components] == [COLLAGEN]


def test_fr_2_4_a_name_that_merely_starts_the_same_is_not_a_match() -> None:
    """FR-2.4, FR-1.13: a looser rule would tie a claim to the wrong product."""
    amount = reviewed("30.00", items=[damaged("Liposomal")])

    assert amount.components == ()


def test_fr_1_13_an_item_matching_two_invoice_lines_is_never_narrowed_to_one() -> None:
    """FR-1.13: choosing between two similar products is the judgement this system refuses.

    CASE-1002 is the real example — two 24oz CleanBoss bottles at different prices. The
    figure is still reviewed against the cap, so a run learns both things at once.
    """
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
    """FR-2.4: claiming five of two invoiced items cannot be right, and only ever lowers it."""
    amount = reviewed(
        "30.00",
        items=[damaged(COLLAGEN, quantity=5, sku="COLLAGEN1")],
        invoice=invoice_of(invoice_line(COLLAGEN, "COLLAGEN1", 2, "52.00")),
    )

    assert [component.quantity for component in amount.components] == [2]
    assert amount.items_total_usd == Decimal("104.00")


def test_fr_1_18_no_invoice_means_no_item_context_and_the_figure_still_stands() -> None:
    """FR-1.18: the invoice is where item prices come from, and it is not the amount.

    A shipment ShipBob will not price leaves a representative without the comparison, which
    is worth knowing — but it does not by itself invalidate what the investigation judged.
    The rules decide what to do about that, not this function.
    """
    amount = reviewed("30.00", invoice=None)

    assert amount.components == ()
    assert amount.items_total_usd == Decimal("0.00")
    assert amount.priced_from is None
    assert amount.amount_usd == Decimal("30.00")


def test_fr_1_18_an_item_that_is_not_on_the_invoice_is_never_priced_from_somewhere_else() -> None:
    """FR-1.18: falling back to the order would show a price the report did not come from."""
    amount = reviewed("30.00", items=[damaged("Beef Trachea Chews")])

    assert amount.components == ()
    assert amount.priced_from == "INV-342578703"


def test_an_item_the_invoice_prices_at_nothing_still_shows_as_costing_nothing() -> None:
    """CASE-1005 carries a free promotional insert, and nothing says what claiming one does.

    It is left visible rather than decided here: the item shows at $0.00 and whoever reads
    the report can see that is what it was worth.
    """
    free = invoice_of(invoice_line("Insert Card", "INSERT", 1, "0.00"))

    amount = reviewed("5.00", items=[damaged("Insert Card", sku="INSERT")], invoice=free)

    assert amount.items_total_usd == Decimal("0.00")
    assert amount.amount_usd == Decimal("5.00")


# ---------------------------------------------------------------------------
# Nothing to pay (FR-1.15)
# ---------------------------------------------------------------------------


def test_a_figure_of_nothing_is_not_payable() -> None:
    """FR-1.15: recommending a payment of nothing would put an empty email in front of a merchant."""
    amount = reviewed("0")

    assert amount.amount_usd == Decimal("0.00")
    assert amount.is_payable is False


def test_nfr_1_the_same_figure_reviewed_twice_comes_out_the_same() -> None:
    """NFR-1: everything around the model's judgement is still repeatable.

    The judgement itself is not, which is the cost of the reversal and is recorded in
    DESIGN.md rather than papered over here.
    """
    assert reviewed("40.00") == reviewed("40.00")
