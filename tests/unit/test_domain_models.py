from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from claim_agent.domain.dates import whole_days_between
from claim_agent.domain.models import Case, DraftedEmail, Order, OrderLineItem, Shipment

# Taken from the CASE-1001 example in REQUIREMENTS.md.
FILED_AT = datetime(2026, 2, 19, 14, 20, 16, tzinfo=UTC)


def make_case(**overrides: Any) -> Case:
    """Build a case with only the required fields, so a test can vary the one it is about."""
    fields: dict[str, Any] = {"case_id": "CASE-1001", "created_date": FILED_AT}
    fields.update(overrides)
    return Case(**fields)


def test_a_time_without_a_timezone_is_refused() -> None:
    """FR-0.6: a time with no timezone would be read differently on different machines."""
    with pytest.raises(ValidationError):
        make_case(created_date=datetime(2026, 2, 19, 14, 20, 16))


def test_the_same_instant_written_three_ways_is_stored_identically() -> None:
    """FR-0.6: ShipBob's `+0000`, a plain `Z`, and another offset all name one instant."""
    shipbob_style = make_case(created_date="2026-02-11T11:36:14.000+0000")
    zulu_style = make_case(created_date="2026-02-11T11:36:14Z")
    berlin_style = make_case(created_date="2026-02-11T12:36:14+01:00")

    assert shipbob_style.created_date == zulu_style.created_date == berlin_style.created_date
    assert berlin_style.created_date.tzinfo is UTC


@pytest.mark.parametrize("absent", [None, "", "   ", "\n"])
def test_blank_text_counts_as_nothing_given(absent: str | None) -> None:
    """FR-0.2: an empty shipment id must not look like an answer."""
    assert make_case(shipment_id=absent).shipment_id is None


def test_text_that_is_actually_there_is_kept() -> None:
    """FR-0.2: only blanks are dropped; a real value passes through untouched."""
    assert make_case(shipment_id="342578703").shipment_id == "342578703"


def test_a_value_that_is_not_text_is_still_reported_as_wrong() -> None:
    """FR-0.2: the blank check hands anything else on, so pydantic reports its own error."""
    with pytest.raises(ValidationError):
        make_case(description=5)


def test_a_shipment_that_says_nothing_about_insurance_is_refused() -> None:
    """FR-0.2: an insured shipment must never be treated as uninsured by default."""
    with pytest.raises(ValidationError):
        Shipment.model_validate({"shipment_id": "342578703"})


def test_a_case_with_no_filing_date_is_refused() -> None:
    """FR-0.2: the age check measures to the moment the claim was filed, so it must exist."""
    with pytest.raises(ValidationError):
        Case.model_validate({"case_id": "CASE-1001"})


def test_a_line_is_worth_its_price_times_how_many() -> None:
    """FR-0.5: quantity counts, so two of a thing is worth twice one of it."""
    line = OrderLineItem(name="Vitamin C Serum", quantity=2, unit_price=Decimal("12.99"))

    assert line.line_total == Decimal("25.98")


def test_order_value_is_added_up_from_its_lines() -> None:
    """FR-0.5: the CASE-1001 order, which ShipBob gives no total for."""
    order = Order(
        order_id="334291211",
        line_items=(
            OrderLineItem(
                name="Additional Collagen Ampoule Duo", quantity=1, unit_price=Decimal("38.00")
            ),
            OrderLineItem(
                name="Liposomal Tripeptide Collagen", quantity=1, unit_price=Decimal("52.00")
            ),
        ),
    )

    assert order.total_value == Decimal("90.00")


def test_order_value_counts_multiples_of_the_same_product() -> None:
    """FR-0.5: the CASE-1002 order, where one line has a quantity of two."""
    order = Order(
        order_id="334291212",
        line_items=(
            OrderLineItem(name="Vitamin C Serum", quantity=1, unit_price=Decimal("24.99")),
            OrderLineItem(name="Hydrating Toner", quantity=2, unit_price=Decimal("12.99")),
            OrderLineItem(name="Night Cream", quantity=1, unit_price=Decimal("14.99")),
        ),
    )

    assert order.total_value == Decimal("65.96")


def test_order_value_is_exact_money_and_keeps_its_cents() -> None:
    """NFR-2: money never becomes a floating point number, and never loses trailing zeros."""
    order = Order(
        order_id="334291211",
        line_items=(
            OrderLineItem(
                name="Additional Collagen Ampoule Duo", quantity=1, unit_price=Decimal("38.00")
            ),
            OrderLineItem(
                name="Liposomal Tripeptide Collagen", quantity=1, unit_price=Decimal("52.00")
            ),
        ),
    )

    assert isinstance(order.total_value, Decimal)
    assert str(order.total_value) == "90.00"
    assert TypeAdapter(Decimal).dump_json(order.total_value) == b'"90.00"'


def test_an_order_with_no_lines_is_worth_nothing_rather_than_failing() -> None:
    """FR-0.5: an unreadable or empty order still gives a figure the caller can judge."""
    assert Order(order_id="334291211").total_value == Decimal("0.00")


def test_a_drafted_email_cannot_claim_to_have_been_sent() -> None:
    """FR-1.17: a draft is a draft, however confident the recommendation behind it."""
    with pytest.raises(ValidationError):
        DraftedEmail(to="sakukreja@shipbob.com", subject="Your claim", body="...", is_draft=False)


def test_a_drafted_email_may_have_no_recipient_yet() -> None:
    """FR-0.4: a case with no contact email still gets a draft; the rep supplies the address."""
    draft = DraftedEmail(to=None, subject="Your claim", body="...")

    assert draft.to is None
    assert draft.is_draft is True


def test_the_facts_of_a_claim_cannot_be_edited_after_they_are_read() -> None:
    """FR-0.6: the same case has to produce the same verdict, so its facts do not move."""
    case = make_case()

    with pytest.raises(ValidationError):
        # mypy already knows this field cannot be assigned to; the test is that the
        # running system refuses it too.
        case.status = "Closed"  # type: ignore[misc]


# Day counting — the arithmetic behind the age check (FR-0.2).
# Dates from the CASE-1004 example in REQUIREMENTS.md.
CASE_1004_DELIVERED = datetime(2025, 12, 26, 12, 13, 36, tzinfo=UTC)
CASE_1004_FILED = datetime(2026, 3, 9, 18, 51, 42, tzinfo=UTC)


def test_the_worked_example_comes_to_seventy_three_days() -> None:
    """FR-0.2: delivered 26 December, filed 9 March — the case REQUIREMENTS.md counts for us."""
    assert whole_days_between(CASE_1004_DELIVERED, CASE_1004_FILED) == 73


def test_counting_backwards_gives_a_negative_number() -> None:
    """FR-0.2: a case filed before its own delivery date is real data, not an error here."""
    assert whole_days_between(CASE_1004_FILED, CASE_1004_DELIVERED) == -73


def test_two_minutes_either_side_of_midnight_is_one_day() -> None:
    """FR-0.2: whole calendar days, not elapsed hours, is how a person reads two dates."""
    delivered = datetime(2026, 2, 11, 23, 59, tzinfo=UTC)
    filed = datetime(2026, 2, 12, 0, 1, tzinfo=UTC)

    assert whole_days_between(delivered, filed) == 1


def test_hours_apart_on_the_same_date_is_no_days_at_all() -> None:
    """FR-0.2: a claim filed the same day it was delivered is nought days old."""
    delivered = datetime(2026, 2, 11, 1, 0, tzinfo=UTC)
    filed = datetime(2026, 2, 11, 23, 0, tzinfo=UTC)

    assert whole_days_between(delivered, filed) == 0


def test_the_count_uses_the_utc_date_not_the_local_one() -> None:
    """FR-0.6: the same two moments have to count the same wherever they were written."""
    delivered = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    filed = datetime(2026, 3, 9, 23, 30, tzinfo=timezone(timedelta(hours=-5)))

    assert whole_days_between(delivered, filed) == 1


def test_counting_days_from_a_time_with_no_timezone_is_refused() -> None:
    """FR-0.6: guessing the timezone would make the answer depend on the machine."""
    with pytest.raises(ValueError, match="timezone"):
        whole_days_between(datetime(2026, 2, 11), CASE_1004_FILED)
