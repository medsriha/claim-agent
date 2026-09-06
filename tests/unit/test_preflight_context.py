from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1004,
    ORDER_1001,
    ORDER_1002,
    ORDER_1004,
    SHIPMENT_1001,
    order_line_item,
    order_payload,
)

from claim_agent.domain.models import Case, MerchantCorrection, Order, Shipment
from claim_agent.policy import Policy
from claim_agent.preflight.context import build_context
from claim_agent.preflight.models import CaseRecord, DeliveryDate

HIGH_VALUE_POLICY = Policy(high_value_order_usd=Decimal("500.00"), high_value_inclusive=True)


def a_record(
    case_payload_used: dict[str, object] = CASE_1001,
    order_payload_used: dict[str, object] | None = ORDER_1001,
) -> CaseRecord:
    return CaseRecord(
        case=Case.model_validate(case_payload_used),
        shipment=Shipment.model_validate(SHIPMENT_1001),
        order=Order.model_validate(order_payload_used) if order_payload_used else None,
    )


def delivered_on(moment: datetime | None) -> DeliveryDate:
    if moment is None:
        return DeliveryDate(value=None, source="none", case_value=None, shipment_value=None)
    return DeliveryDate(value=moment, source="case", case_value=moment, shipment_value=moment)


def delivery_from(case_payload_used: dict[str, Any]) -> DeliveryDate:
    return delivered_on(Case.model_validate(case_payload_used).delivered_date)


def an_order_worth(amount: str) -> dict[str, object]:
    return order_payload(line_items=[order_line_item(quantity=1, unit_price=float(amount))])


def test_the_order_value_is_the_line_items_added_up() -> None:
    context = build_context(a_record(), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY)

    assert context.order_value_usd == Decimal("90.00")


def test_how_many_of_a_product_were_ordered_counts_towards_the_value() -> None:
    context = build_context(
        a_record(CASE_1002, ORDER_1002),
        delivery_from(CASE_1002),
        (),
        HIGH_VALUE_POLICY,
    )

    assert context.order_value_usd == Decimal("65.96")


def test_the_order_value_is_an_exact_amount_of_money() -> None:
    context = build_context(a_record(), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY)

    assert isinstance(context.order_value_usd, Decimal)
    assert str(context.order_value_usd) == "90.00"


def test_an_order_we_could_not_read_has_no_value_rather_than_no_money() -> None:
    context = build_context(
        a_record(order_payload_used=None), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY
    )

    assert context.order_value_usd is None
    assert context.is_high_value is False


def test_an_order_with_nothing_on_it_is_worth_nothing_which_is_not_unknown() -> None:
    context = build_context(
        a_record(order_payload_used=order_payload(line_items=[])),
        delivery_from(CASE_1001),
        (),
        HIGH_VALUE_POLICY,
    )

    assert context.order_value_usd == Decimal("0.00")
    assert context.order_value_usd is not None
    assert context.is_high_value is False


@pytest.mark.parametrize(
    ("order_total", "expected"),
    [("499.99", False), ("500.00", True), ("500.01", True)],
)
def test_an_order_is_high_value_once_it_reaches_the_threshold(
    order_total: str, expected: bool
) -> None:
    context = build_context(
        a_record(order_payload_used=an_order_worth(order_total)),
        delivery_from(CASE_1001),
        (),
        HIGH_VALUE_POLICY,
    )

    assert context.is_high_value is expected


def test_landing_exactly_on_the_threshold_can_be_set_to_not_count() -> None:
    exclusive = Policy(high_value_order_usd=Decimal("500.00"), high_value_inclusive=False)

    context = build_context(
        a_record(order_payload_used=an_order_worth("500.00")),
        delivery_from(CASE_1001),
        (),
        exclusive,
    )

    assert context.is_high_value is False


def test_changing_the_high_value_figure_changes_the_answer() -> None:
    ordinary = build_context(a_record(), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY)
    lowered = Policy(high_value_order_usd=Decimal("50.00"), high_value_inclusive=True)

    flagged = build_context(a_record(), delivery_from(CASE_1001), (), lowered)

    assert ordinary.is_high_value is False
    assert flagged.is_high_value is True


def test_the_days_counted_are_from_delivery_to_the_claim_being_filed() -> None:
    context = build_context(
        a_record(CASE_1004, ORDER_1004), delivery_from(CASE_1004), (), HIGH_VALUE_POLICY
    )

    assert context.days_since_delivery == 73


def test_a_claim_filed_soon_after_delivery_counts_only_those_days() -> None:
    context = build_context(a_record(), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY)

    assert context.days_since_delivery == 8


def test_with_no_delivery_date_there_is_nothing_to_count() -> None:
    context = build_context(a_record(), delivered_on(None), (), HIGH_VALUE_POLICY)

    assert context.days_since_delivery is None
    assert context.delivered_date is None


def test_the_delivery_date_used_is_the_one_the_checks_settled_on() -> None:
    settled_on = datetime(2026, 2, 10, 9, 0, 0, tzinfo=UTC)

    context = build_context(a_record(), delivered_on(settled_on), (), HIGH_VALUE_POLICY)

    assert context.delivered_date == settled_on
    assert context.days_since_delivery == 9


def test_what_a_rep_corrected_before_is_passed_on_in_the_order_given() -> None:
    older = MerchantCorrection(
        user_id="334430",
        case_id="CASE-1001",
        summary="Rep paid for the ampoule duo only.",
        recorded_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
    )
    newer = MerchantCorrection(
        user_id="334430",
        case_id="CASE-1006",
        summary="Rep asked for a photograph of the outer box every time.",
        recorded_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
    )

    context = build_context(a_record(), delivery_from(CASE_1001), [older, newer], HIGH_VALUE_POLICY)

    assert context.merchant_corrections == (older, newer)


def test_a_merchant_with_no_history_carries_no_corrections() -> None:
    context = build_context(a_record(), delivery_from(CASE_1001), (), HIGH_VALUE_POLICY)

    assert context.merchant_corrections == ()
