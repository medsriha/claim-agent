from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    CONSTRUCTED_INSURED_SHIPMENT,
    CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
    CONSTRUCTED_LOST_IN_TRANSIT_CASE,
    ORDER_1001,
    SHIPMENT_1001,
    SHIPMENT_1004,
    case_payload,
    order_payload,
    shipment_payload,
    without,
)

from claim_agent.domain.models import Case, GateName, Order, Shipment, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.gates import (
    EMAIL_REASON_ORDER,
    check_age,
    check_claim_type,
    check_insurance,
    check_key_information,
    evaluate_gates,
    resolve_delivered_date,
    terminal_reasons,
)
from claim_agent.preflight.models import CaseRecord, GateResult

DELIVERED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def case_from(payload: dict[str, object]) -> Case:
    return Case.model_validate(payload)


def shipment_from(payload: dict[str, object]) -> Shipment:
    return Shipment.model_validate(payload)


def order_from(payload: dict[str, object]) -> Order:
    return Order.model_validate(payload)


def record_of(
    case: dict[str, object],
    shipment: dict[str, object] | None,
    order: dict[str, object] | None,
) -> CaseRecord:
    return CaseRecord(
        case=case_from(case),
        shipment=None if shipment is None else shipment_from(shipment),
        order=None if order is None else order_from(order),
    )


def complete_record(**case_overrides: object) -> CaseRecord:
    return record_of(case_payload(**case_overrides), shipment_payload(), order_payload())


def age_of(record: CaseRecord, policy: Policy) -> GateResult:
    return check_age(resolve_delivered_date(record), record.case, policy)


def filed_days_after_delivery(days: int) -> CaseRecord:
    filed_at = DELIVERED + timedelta(days=days)
    return record_of(
        case_payload(delivered_date=DELIVERED.isoformat(), created_date=filed_at.isoformat()),
        shipment_payload(delivered_date=DELIVERED.isoformat()),
        order_payload(),
    )


def test_fr_0_2_a_claim_filed_eight_days_after_delivery_is_not_too_old() -> None:
    gate = age_of(record_of(CASE_1001, SHIPMENT_1001, ORDER_1001), Policy())

    assert gate.gate is GateName.AGE
    assert gate.passed
    assert gate.reason is None
    assert gate.observed["days_since_delivery"] == "8"
    assert "8 days" in gate.explanation


def test_fr_0_2_a_claim_filed_seventy_three_days_after_delivery_is_too_old() -> None:
    gate = age_of(record_of(CASE_1004, SHIPMENT_1004, None), Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.CLAIM_TOO_OLD
    assert gate.observed["days_since_delivery"] == "73"
    assert gate.observed["age_limit_days"] == "60"
    assert "73 days" in gate.explanation


def test_fr_0_2_a_claim_filed_on_the_limit_day_passes_when_that_day_still_counts() -> None:
    gate = age_of(filed_days_after_delivery(60), Policy(max_claim_age_days=60))

    assert gate.passed
    assert gate.observed["days_since_delivery"] == "60"
    assert gate.observed["limit_day_still_counts"] == "yes"


def test_fr_0_2_a_claim_filed_one_day_past_the_limit_is_too_old() -> None:
    gate = age_of(filed_days_after_delivery(61), Policy(max_claim_age_days=60))

    assert not gate.passed
    assert gate.reason is TerminalReason.CLAIM_TOO_OLD


def test_fr_0_2_the_limit_day_is_already_too_late_when_the_policy_says_it_does_not_count() -> None:
    policy = Policy(max_claim_age_days=60, age_limit_inclusive=False)
    gate = age_of(filed_days_after_delivery(60), policy)

    assert not gate.passed
    assert gate.reason is TerminalReason.CLAIM_TOO_OLD
    assert gate.observed["limit_day_still_counts"] == "no"


def test_fr_0_2_the_parcels_delivery_date_is_used_when_the_claim_has_none() -> None:
    record = record_of(case_payload(delivered_date=None), shipment_payload(), order_payload())

    delivery = resolve_delivered_date(record)
    gate = check_age(delivery, record.case, Policy())

    assert delivery.source == "shipment"
    assert gate.observed["delivered_date_taken_from"] == "the shipment record"
    assert gate.observed["case_delivered_date"] == "not recorded"
    assert gate.observed["days_since_delivery"] == "8"


def test_fr_0_2_the_claims_own_delivery_date_is_used_when_both_records_have_one() -> None:
    record = record_of(CASE_1001, SHIPMENT_1001, ORDER_1001)

    delivery = resolve_delivered_date(record)

    assert delivery.source == "case"
    assert delivery.value == delivery.case_value


def test_fr_0_2_disagreeing_delivery_dates_are_both_reported_and_the_claims_date_wins() -> None:
    record = record_of(
        CASE_1001,
        shipment_payload(delivered_date="2026-02-12T11:36:14.000+0000"),
        ORDER_1001,
    )

    delivery = resolve_delivered_date(record)
    gate = check_age(delivery, record.case, Policy())

    assert delivery.sources_disagree
    assert gate.passed
    assert gate.observed["case_delivered_date"] == "2026-02-11T11:36:14+00:00"
    assert gate.observed["shipment_delivered_date"] == "2026-02-12T11:36:14+00:00"
    assert gate.observed["delivered_date_used"] == gate.observed["case_delivered_date"]
    assert "different delivery dates" in gate.explanation


def test_fr_0_2_a_claim_with_no_delivery_date_anywhere_fails_as_missing_information() -> None:
    record = record_of(
        case_payload(delivered_date=None),
        shipment_payload(delivered_date=None),
        order_payload(),
    )

    gate = age_of(record, Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.MISSING_KEY_INFORMATION
    assert gate.observed["days_since_delivery"] == "not known"
    assert gate.observed["delivered_date_taken_from"] == "neither record"


def test_fr_0_2_the_same_moment_written_two_ways_gives_the_same_day_count() -> None:
    with_offset = complete_record(
        delivered_date="2026-02-11T11:36:14.000+0000",
        created_date="2026-02-19T14:20:16.000+0000",
    )
    with_zulu = complete_record(
        delivered_date="2026-02-11T11:36:14.000Z",
        created_date="2026-02-19T14:20:16.000Z",
    )

    assert age_of(with_offset, Policy()).observed == age_of(with_zulu, Policy()).observed


def test_fr_0_2_a_claim_filed_before_its_own_delivery_date_passes_with_a_negative_count() -> None:
    record = complete_record(
        delivered_date="2026-02-19T14:20:16.000+0000",
        created_date="2026-02-11T11:36:14.000+0000",
    )

    gate = age_of(record, Policy())

    assert gate.passed
    assert gate.reason is None
    assert gate.observed["days_since_delivery"] == "-8"
    assert "before the delivery date on record" in gate.explanation


def test_fr_0_7_raising_the_age_limit_to_ninety_days_lets_the_old_claim_through() -> None:
    record = record_of(CASE_1004, SHIPMENT_1004, None)

    assert not age_of(record, Policy(max_claim_age_days=60)).passed
    assert age_of(record, Policy(max_claim_age_days=90)).passed


@pytest.mark.parametrize(
    "sample_case",
    [CASE_1001, CASE_1002, CASE_1003, CASE_1004, CASE_1005],
    ids=["case-1001", "case-1002", "case-1003", "case-1004", "case-1005"],
)
def test_fr_0_2_every_sample_claim_is_a_damaged_in_transit_claim(
    sample_case: dict[str, object],
) -> None:
    gate = check_claim_type(case_from(sample_case), Policy())

    assert gate.gate is GateName.CLAIM_TYPE
    assert gate.passed
    assert gate.reason is None


@pytest.mark.parametrize(
    "written_as",
    [
        "Claim | Damaged in Transit",
        "claim | damaged in transit",
        "CLAIM | DAMAGED IN TRANSIT",
        "  Claim |  Damaged in Transit  ",
        "Claim |\tDamaged in\nTransit",
    ],
)
def test_fr_0_2_capitals_and_extra_spacing_do_not_change_the_claim_type(written_as: str) -> None:
    gate = check_claim_type(case_from(case_payload(sub_category=written_as)), Policy())

    assert gate.passed
    assert gate.observed["claim_type_compared"] == "claim | damaged in transit"


def test_fr_0_2_a_lost_in_transit_claim_is_the_wrong_kind() -> None:
    gate = check_claim_type(case_from(CONSTRUCTED_LOST_IN_TRANSIT_CASE), Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.WRONG_CLAIM_TYPE
    assert gate.observed["claim_type"] == "Claim | Lost in Transit"


@pytest.mark.parametrize(
    "claim_type",
    [
        "Claim | Damaged in Transit by USPS",
        "Claim | Damaged in Transit - Insured",
    ],
)
def test_fr_0_2_claim_type_details_after_the_handled_prefix_are_accepted(
    claim_type: str,
) -> None:
    gate = check_claim_type(case_from(case_payload(sub_category=claim_type)), Policy())

    assert gate.passed
    assert gate.reason is None


@pytest.mark.parametrize(
    "case",
    [
        without(case_payload(), "sub_category"),
        case_payload(sub_category=None),
        case_payload(sub_category="   "),
    ],
    ids=["absent", "null", "spaces"],
)
def test_fr_0_2_a_claim_that_does_not_say_what_kind_it_is_is_turned_away(
    case: dict[str, object],
) -> None:
    gate = check_claim_type(case_from(case), Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.WRONG_CLAIM_TYPE
    assert gate.observed["claim_type"] == "not recorded"


def test_fr_0_7_changing_the_handled_claim_type_changes_what_passes() -> None:
    policy = Policy(damaged_in_transit_sub_category="Claim | Lost in Transit")

    assert not check_claim_type(case_from(CASE_1001), policy).passed
    assert check_claim_type(case_from(CONSTRUCTED_LOST_IN_TRANSIT_CASE), policy).passed


def test_fr_0_2_a_complete_claim_has_everything_needed_to_investigate() -> None:
    gate = check_key_information(record_of(CASE_1001, SHIPMENT_1001, ORDER_1001), Policy())

    assert gate.gate is GateName.KEY_INFORMATION
    assert gate.passed
    assert gate.reason is None
    assert gate.observed["missing"] == ""


MISSING_FIELDS = [
    ("shipment_id", "the shipment number it relates to"),
    ("order_id", "the order number it relates to"),
    ("description", "a description of what happened"),
]


@pytest.mark.parametrize(("field_name", "expected_label"), MISSING_FIELDS)
def test_fr_0_2_a_field_the_claim_never_carried_is_missing(
    field_name: str, expected_label: str
) -> None:
    record = record_of(without(case_payload(), field_name), shipment_payload(), order_payload())

    gate = check_key_information(record, Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.MISSING_KEY_INFORMATION
    assert gate.observed["missing"] == expected_label


@pytest.mark.parametrize("empty_value", [None, "", "   "], ids=["null", "empty", "spaces"])
@pytest.mark.parametrize(("field_name", "expected_label"), MISSING_FIELDS)
def test_fr_0_2_a_field_that_is_present_but_empty_is_missing(
    field_name: str, empty_value: str | None, expected_label: str
) -> None:
    record = record_of(
        case_payload(**{field_name: empty_value}), shipment_payload(), order_payload()
    )

    gate = check_key_information(record, Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.MISSING_KEY_INFORMATION
    assert gate.observed["missing"] == expected_label


def test_fr_0_2_a_parcel_record_that_could_not_be_read_counts_as_missing() -> None:
    gate = check_key_information(record_of(CASE_1001, None, ORDER_1001), Policy())

    assert not gate.passed
    assert gate.reason is TerminalReason.MISSING_KEY_INFORMATION
    assert gate.observed["missing"] == "a shipment matching the number on it"


def test_fr_0_2_an_order_record_that_could_not_be_read_counts_as_missing() -> None:
    gate = check_key_information(record_of(CASE_1001, SHIPMENT_1001, None), Policy())

    assert not gate.passed
    assert gate.observed["missing"] == "an order matching the number on it"


def test_fr_0_2_the_result_tells_a_missing_id_apart_from_a_record_that_could_not_be_read() -> None:
    no_id = record_of(without(case_payload(), "shipment_id"), None, order_payload())
    unreadable = record_of(case_payload(), None, order_payload())

    no_id_gate = check_key_information(no_id, Policy())
    unreadable_gate = check_key_information(unreadable, Policy())

    assert no_id_gate.observed["shipment_id"] == "not recorded"
    assert no_id_gate.observed["shipment_record"] == "not looked up, because the claim gives no id"
    assert unreadable_gate.observed["shipment_id"] == "342578703"
    assert unreadable_gate.observed["shipment_record"] == "could not be read"


def test_fr_0_2_several_missing_things_are_all_listed_in_a_fixed_order() -> None:
    record = record_of(without(case_payload(), "order_id", "description"), None, None)

    gate = check_key_information(record, Policy())

    assert gate.observed["missing"] == (
        "a shipment matching the number on it, the order number it relates to, a description of what happened"
    )


def test_fr_0_7_a_description_shorter_than_the_minimum_does_not_count_as_one() -> None:
    record = complete_record(description="Broken.")

    assert check_key_information(record, Policy(min_description_length=1)).passed

    gate = check_key_information(record, Policy(min_description_length=50))

    assert not gate.passed
    assert gate.observed["missing"] == "a fuller description of what happened"
    assert gate.observed["description_length"] == "7"


def test_fr_0_2_an_uninsured_parcel_belongs_here() -> None:
    gate = check_insurance(shipment_from(SHIPMENT_1001))

    assert gate.gate is GateName.INSURANCE
    assert gate.passed
    assert gate.observed["is_insured"] == "no"


def test_fr_0_2_an_insured_parcel_is_routed_away() -> None:
    gate = check_insurance(shipment_from(CONSTRUCTED_INSURED_SHIPMENT))

    assert not gate.passed
    assert gate.reason is TerminalReason.SHIPMENT_INSURED
    assert gate.observed["is_insured"] == "yes"


@pytest.mark.parametrize(
    "claim_type",
    [
        "Claim | Damaged in Transit - Insured",
        "Claim | INSURED Damaged in Transit",
    ],
)
def test_fr_0_2_an_insured_claim_type_overrides_a_false_shipment_flag(
    claim_type: str,
) -> None:
    gate = check_insurance(shipment_from(SHIPMENT_1001), claim_type)

    assert not gate.passed
    assert gate.reason is TerminalReason.SHIPMENT_INSURED
    assert gate.observed["is_insured"] == "no"
    assert gate.observed["claim_type_indicates_insured"] == "yes"


def test_fr_0_2_insured_must_be_a_word_in_the_claim_type() -> None:
    gate = check_insurance(shipment_from(SHIPMENT_1001), "Claim | Uninsured Damage")

    assert gate.passed
    assert gate.observed["claim_type_indicates_insured"] == "no"


def test_fr_0_2_a_parcel_we_do_not_have_fails_because_its_insurance_is_unknown() -> None:
    gate = check_insurance(None)

    assert not gate.passed
    assert gate.reason is TerminalReason.MISSING_KEY_INFORMATION
    assert gate.observed["is_insured"] == "not known"


def everything_wrong_record() -> CaseRecord:
    return record_of(
        without(
            case_payload(
                case_id="CASE-9101",
                sub_category="Claim | Lost in Transit",
                delivered_date="2025-12-26T12:13:36.000+0000",
                created_date="2026-03-09T18:51:42.000+0000",
            ),
            "order_id",
        ),
        shipment_payload(delivered_date="2025-12-26T12:13:36.000+0000", is_insured=True),
        order_payload(),
    )


def test_fr_0_2_all_four_checks_run_even_when_the_first_one_fails() -> None:
    record = everything_wrong_record()

    gates = evaluate_gates(record, resolve_delivered_date(record), Policy())

    assert len(gates) == 4
    assert tuple(gate.gate for gate in gates) == tuple(GateName)
    assert not any(gate.passed for gate in gates)


def test_fr_0_2_a_claim_that_clears_everything_has_no_reason_to_be_stopped() -> None:
    record = record_of(CASE_1001, SHIPMENT_1001, ORDER_1001)

    gates = evaluate_gates(record, resolve_delivered_date(record), Policy())

    assert all(gate.passed for gate in gates)
    assert terminal_reasons(gates) == ()


def test_fr_0_2_an_insured_claim_type_is_routed_out_when_the_shipment_says_false() -> None:
    record = record_of(
        CONSTRUCTED_INSURED_SUBCATEGORY_CASE,
        shipment_payload(shipment_id="990000003", order_id="990000003", is_insured=False),
        order_payload(order_id="990000003", user_id="990000003"),
    )

    gates = evaluate_gates(record, resolve_delivered_date(record), Policy())

    assert terminal_reasons(gates) == (TerminalReason.SHIPMENT_INSURED,)


def test_fr_0_3_reasons_come_back_in_a_fixed_order_led_by_insurance() -> None:
    record = everything_wrong_record()

    gates = evaluate_gates(record, resolve_delivered_date(record), Policy())

    assert terminal_reasons(gates) == (
        TerminalReason.SHIPMENT_INSURED,
        TerminalReason.CLAIM_TOO_OLD,
        TerminalReason.WRONG_CLAIM_TYPE,
        TerminalReason.MISSING_KEY_INFORMATION,
    )


def test_fr_0_3_a_reason_three_checks_all_give_is_only_said_once() -> None:
    record = record_of(case_payload(delivered_date=None), None, order_payload())

    gates = evaluate_gates(record, resolve_delivered_date(record), Policy())
    failed = [gate for gate in gates if not gate.passed]

    assert len(failed) == 3
    assert terminal_reasons(gates) == (TerminalReason.MISSING_KEY_INFORMATION,)


def test_fr_0_2_being_insured_is_not_one_of_the_reasons_the_email_explains() -> None:
    assert TerminalReason.SHIPMENT_INSURED not in EMAIL_REASON_ORDER
    assert set(EMAIL_REASON_ORDER) == set(TerminalReason) - {TerminalReason.SHIPMENT_INSURED}


def test_fr_0_6_the_same_claim_screened_twice_gives_exactly_the_same_result() -> None:
    record = everything_wrong_record()

    first = evaluate_gates(record, resolve_delivered_date(record), Policy())
    second = evaluate_gates(record, resolve_delivered_date(record), Policy())

    assert [gate.model_dump() for gate in first] == [gate.model_dump() for gate in second]
    assert [list(gate.observed) for gate in first] == [list(gate.observed) for gate in second]
