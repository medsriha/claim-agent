from __future__ import annotations

from datetime import date

from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1003,
    CASE_1004,
    CASE_1005,
    SHIPMENT_1001,
    SHIPMENT_1002,
    SHIPMENT_1003,
    SHIPMENT_1004,
    SHIPMENT_1005,
    case_payload,
    shipment_payload,
)

from claim_agent.domain.case_facts import (
    CaseFacts,
    Contradiction,
    ContradictionKind,
    DamageType,
    DefectType,
    read_case_facts,
)
from claim_agent.domain.models import Case, Shipment


def facts_for(case: dict[str, object], shipment: dict[str, object] | None = None) -> CaseFacts:
    return read_case_facts(
        Case.model_validate(case),
        None if shipment is None else Shipment.model_validate(shipment),
    )


def facts_from(description: str | None) -> CaseFacts:
    return facts_for(case_payload(description=description), SHIPMENT_1001)


def kinds(facts: CaseFacts) -> tuple[ContradictionKind, ...]:
    return tuple(contradiction.kind for contradiction in facts.contradictions)


def one(facts: CaseFacts, kind: ContradictionKind) -> Contradiction:
    matching = [item for item in facts.contradictions if item.kind is kind]
    assert len(matching) == 1, f"expected exactly one {kind} disagreement, got {kinds(facts)}"
    return matching[0]


def test_reads_case_1001_which_is_written_without_any_field_names() -> None:
    facts = facts_for(CASE_1001, SHIPMENT_1001)

    assert facts.shipment_id == "342578703"
    assert facts.damage_type == "Damage due to poor/bad packaging"
    assert facts.damage_type_recognised is DamageType.POOR_PACKAGING
    assert facts.defect_type == "Both product and shipping box damaged"
    assert facts.defect_type_recognised is DefectType.PRODUCT_AND_BOX
    assert facts.affected_order_count == 1
    assert facts.last_carrier_tracking_date is None
    assert facts.carrier is None
    assert facts.unreadable == ()

    assert facts.contradictions == ()


def test_reads_case_1002_which_uses_the_claim_forms_field_names() -> None:
    facts = facts_for(CASE_1002, SHIPMENT_1002)

    assert facts.shipment_id == "344745459"
    assert facts.damage_type == "Damage due to poor/bad packaging"
    assert facts.damage_type_recognised is DamageType.POOR_PACKAGING
    assert facts.defect_type == "Both product and shipping box damaged"
    assert facts.defect_type_recognised is DefectType.PRODUCT_AND_BOX
    assert facts.affected_order_count == 1
    assert facts.last_carrier_tracking_date == date(2026, 2, 22)
    assert facts.carrier == "Other"
    assert facts.unreadable == ()
    assert kinds(facts) == (ContradictionKind.CARRIER,)


def test_reads_case_1003_which_says_two_orders_were_affected() -> None:
    facts = facts_for(CASE_1003, SHIPMENT_1003)

    assert facts.shipment_id == "346106093"
    assert facts.damage_type == "Damage due to carrier mishandling"
    assert facts.damage_type_recognised is DamageType.CARRIER_MISHANDLING

    assert facts.defect_type is None
    assert facts.defect_type_recognised is None
    assert facts.affected_order_count == 2
    assert facts.last_carrier_tracking_date == date(2026, 2, 24)
    assert facts.carrier == "Other"
    assert facts.unreadable == ()
    assert kinds(facts) == (
        ContradictionKind.CARRIER,
        ContradictionKind.AFFECTED_ORDER_COUNT,
        ContradictionKind.LAST_TRACKING_DATE,
    )


def test_reads_case_1004_whose_tracking_date_is_months_after_delivery() -> None:
    facts = facts_for(CASE_1004, SHIPMENT_1004)

    assert facts.shipment_id == "330936165"
    assert facts.damage_type == "Damage due to poor/bad packaging"
    assert facts.damage_type_recognised is DamageType.POOR_PACKAGING
    assert facts.defect_type == "Product damaged, but shipping box is intact"
    assert facts.defect_type_recognised is DefectType.PRODUCT_ONLY
    assert facts.affected_order_count == 1
    assert facts.last_carrier_tracking_date == date(2026, 3, 6)
    assert facts.carrier == "Other"
    assert facts.unreadable == ()
    assert kinds(facts) == (ContradictionKind.CARRIER, ContradictionKind.LAST_TRACKING_DATE)


def test_reads_case_1005_which_has_no_evidence_behind_it() -> None:
    facts = facts_for(CASE_1005, SHIPMENT_1005)

    assert facts.shipment_id == "349164073"
    assert facts.damage_type == "Damage due to carrier mishandling"
    assert facts.damage_type_recognised is DamageType.CARRIER_MISHANDLING
    assert facts.defect_type is None
    assert facts.defect_type_recognised is None
    assert facts.affected_order_count == 1
    assert facts.last_carrier_tracking_date == date(2026, 3, 10)
    assert facts.carrier == "Other"
    assert facts.unreadable == ()
    assert kinds(facts) == (ContradictionKind.CARRIER,)


def test_the_carrier_in_the_description_is_checked_against_the_shipment() -> None:
    disagreement = one(facts_for(CASE_1002, SHIPMENT_1002), ContradictionKind.CARRIER)

    assert disagreement.described == "Other"
    assert disagreement.recorded == "CirroECommerce"
    assert "carrier" in disagreement.why_it_matters

    assert kinds(facts_for(CASE_1001, SHIPMENT_1001)) == ()


def test_a_description_about_a_different_parcel_is_reported() -> None:
    facts = facts_for(
        case_payload(shipment_id="344745459"),
        shipment_payload(shipment_id="344745459"),
    )
    disagreement = one(facts, ContradictionKind.SHIPMENT_ID)

    assert facts.shipment_id == "342578703"
    assert disagreement.described == "342578703"
    assert disagreement.recorded == "344745459"


def test_two_affected_orders_on_a_case_that_names_one_order_is_reported() -> None:
    disagreement = one(facts_for(CASE_1003, SHIPMENT_1003), ContradictionKind.AFFECTED_ORDER_COUNT)

    assert disagreement.described == "2 affected orders"
    assert disagreement.recorded == "one order, 337761802"


def test_no_affected_orders_at_all_is_also_a_disagreement() -> None:
    facts = facts_from("Shipment ID: 342578703. Number of affected orders: 0.")

    assert facts.affected_order_count == 0
    assert one(facts, ContradictionKind.AFFECTED_ORDER_COUNT).described == "0 affected orders"


def test_the_count_is_not_checked_when_the_case_names_no_order() -> None:
    facts = facts_for(
        case_payload(
            description="Shipment ID: 342578703. Number of affected orders: 2.",
            order_id=None,
        ),
        SHIPMENT_1001,
    )

    assert facts.affected_order_count == 2
    assert kinds(facts) == ()


def test_a_tracking_date_that_is_not_the_delivery_day_is_reported() -> None:
    disagreement = one(facts_for(CASE_1004, SHIPMENT_1004), ContradictionKind.LAST_TRACKING_DATE)

    assert disagreement.described == "2026-03-06"
    assert disagreement.recorded == "2025-12-26"


def test_without_the_shipment_record_the_carrier_and_date_are_read_but_not_checked() -> None:
    facts = facts_for(CASE_1003)

    assert facts.carrier == "Other"
    assert facts.last_carrier_tracking_date == date(2026, 2, 24)
    assert kinds(facts) == (ContradictionKind.AFFECTED_ORDER_COUNT,)


def test_a_case_with_no_description_reads_nothing_and_says_why() -> None:
    facts = facts_from(None)

    assert facts.shipment_id is None
    assert facts.damage_type is None
    assert facts.defect_type is None
    assert facts.affected_order_count is None
    assert facts.last_carrier_tracking_date is None
    assert facts.carrier is None
    assert facts.contradictions == ()
    assert facts.unreadable == ("The case carries no description, so there was nothing to read.",)


def test_a_blank_description_counts_as_no_description_at_all() -> None:
    assert facts_from("   ") == facts_from(None)


def test_a_description_carrying_none_of_the_facts_yields_none_of_them() -> None:
    facts = facts_from("The customer rang to say the parcel turned up in a bad way.")

    assert facts.shipment_id is None
    assert facts.damage_type is None
    assert facts.defect_type is None
    assert facts.affected_order_count is None
    assert facts.last_carrier_tracking_date is None
    assert facts.carrier is None
    assert facts.contradictions == ()
    assert facts.unreadable == ()


def test_a_product_with_carrier_in_its_name_is_not_mistaken_for_the_carrier() -> None:
    facts = facts_from(
        "Shipment ID: 342578703. The Carrier Bag Deluxe arrived crushed. "
        "Date of Last Carrier Tracking: February 22, 2026. Carrier: Other."
    )

    assert facts.carrier == "Other"
    assert facts.last_carrier_tracking_date == date(2026, 2, 22)


def test_a_sentence_saying_the_carrier_was_not_at_fault_is_not_read_as_a_cause() -> None:
    facts = facts_from(
        "Shipment ID: 342578703. The customer confirmed this was not damage due to "
        "carrier mishandling."
    )

    assert facts.damage_type is None
    assert facts.damage_type_recognised is None


def test_a_defect_wording_buried_in_a_longer_sentence_is_not_read() -> None:
    facts = facts_from(
        "Shipment ID: 342578703. The customer said both product and shipping box damaged "
        "several other items in the same delivery."
    )

    assert facts.defect_type is None
    assert facts.defect_type_recognised is None


def test_a_labelled_defect_inside_a_longer_sentence_is_still_read() -> None:
    facts = facts_from(
        "Shipment ID: 342578703. Defect Type: Product damaged, but shipping box is intact."
    )

    assert facts.defect_type == "Product damaged, but shipping box is intact"
    assert facts.defect_type_recognised is DefectType.PRODUCT_ONLY


def test_a_cause_nobody_has_seen_before_keeps_its_own_words() -> None:
    facts = facts_from("Shipment ID: 342578703. Damage Type: Damage due to a warehouse forklift.")

    assert facts.damage_type == "Damage due to a warehouse forklift"
    assert facts.damage_type_recognised is None


def test_capitals_and_extra_spacing_do_not_change_what_was_read() -> None:
    facts = facts_from(
        "shipment id:  342578703.   DAMAGE TYPE:   Damage due to carrier mishandling.  "
        "carrier:  Royal Mail Tracked 48."
    )

    assert facts.shipment_id == "342578703"
    assert facts.damage_type_recognised is DamageType.CARRIER_MISHANDLING

    assert kinds(facts) == ()


def test_a_description_answering_the_same_field_twice_refuses_to_choose() -> None:
    facts = facts_from("Shipment ID: 342578703. Correction — Shipment ID: 344745459.")

    assert facts.shipment_id is None
    assert kinds(facts) == ()
    assert len(facts.unreadable) == 1
    assert '"342578703", "344745459"' in facts.unreadable[0]


def test_the_same_answer_given_twice_is_not_a_disagreement() -> None:
    facts = facts_from("Shipment ID: 342578703. To confirm, Shipment ID: 342578703.")

    assert facts.shipment_id == "342578703"
    assert facts.unreadable == ()


def test_a_day_that_does_not_exist_is_reported_rather_than_dropped() -> None:
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: February 30, 2026.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"February 30, 2026"' in facts.unreadable[0]


def test_a_tracking_date_written_as_something_else_is_reported() -> None:
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: unknown.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"unknown"' in facts.unreadable[0]


def test_a_count_written_out_in_words_is_left_unread() -> None:
    facts = facts_from("Shipment ID: 342578703. Number of affected orders: two.")

    assert facts.affected_order_count is None
    assert facts.unreadable == ()


def test_a_shortened_month_name_is_read() -> None:
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: Feb 22, 2026.")

    assert facts.last_carrier_tracking_date == date(2026, 2, 22)


def test_a_date_written_only_in_numbers_is_not_guessed_at() -> None:
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: 11/02/2026.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"11/02/2026"' in facts.unreadable[0]


def test_the_same_claim_is_read_the_same_way_twice() -> None:
    assert facts_for(CASE_1003, SHIPMENT_1003) == facts_for(CASE_1003, SHIPMENT_1003)
