"""Reading the structured facts hidden in a merchant's case description.

The five sample claims write the same facts two different ways. Four of them use
the field names from ShipBob's claim form — `Damage Type:`, `Defect Type:`,
`Number of affected orders:` — and one, CASE-1001, writes the lot as ordinary
sentences with no field names at all. There is a test for each of the five, and
each one checks every value that came out, because a reader who cannot tell what
a description is supposed to yield cannot tell when the reading has gone wrong.

The rest of the file is about the parts that are easy to get wrong: the four ways
a description can disagree with ShipBob's own records, descriptions that say
nothing, and text written to catch out a careless pattern — a product with
"Carrier" in its name, a sentence saying the damage was *not* caused by the
carrier, and a description that answers the same question twice with two
different answers.

No requirement covers this feature; see DESIGN.md. The rules it works under are
FR-0.6 and NFR-1 (the same claim reads the same way every time), FR-1.13 (never
narrow two candidates to one) and NFR-4 (fail toward the human).
"""

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
    """Read one case's description, with or without the shipment to check it against."""
    return read_case_facts(
        Case.model_validate(case),
        None if shipment is None else Shipment.model_validate(shipment),
    )


def facts_from(description: str | None) -> CaseFacts:
    """Read a description of a test's own choosing, on an otherwise ordinary case.

    Everything else on the case is CASE-1001's, so a test that cares only about
    the wording does not have to build a whole claim to say so.
    """
    return facts_for(case_payload(description=description), SHIPMENT_1001)


def kinds(facts: CaseFacts) -> tuple[ContradictionKind, ...]:
    """Which disagreements were reported, in the order they were reported."""
    return tuple(contradiction.kind for contradiction in facts.contradictions)


def one(facts: CaseFacts, kind: ContradictionKind) -> Contradiction:
    """The single reported disagreement of one kind, failing the test if it is absent."""
    matching = [item for item in facts.contradictions if item.kind is kind]
    assert len(matching) == 1, f"expected exactly one {kind} disagreement, got {kinds(facts)}"
    return matching[0]


# ---------------------------------------------------------------------------
# The five real descriptions, read in full
# ---------------------------------------------------------------------------


def test_reads_case_1001_which_is_written_without_any_field_names() -> None:
    """CASE-1001 writes every fact as a plain sentence, and all of them are still read.

    This is the description that has no `Damage Type:` or `Defect Type:` label
    anywhere in it, and says "1 order affected" rather than giving a count after a
    label. It is also the only sample description that names no carrier and no
    tracking date, so both come back empty rather than being filled in from
    somewhere else.
    """
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
    # Nothing disagrees: the parcel and the order count match the case, and the
    # description names neither a carrier nor a date to disagree about.
    assert facts.contradictions == ()


def test_reads_case_1002_which_uses_the_claim_forms_field_names() -> None:
    """CASE-1002 labels every fact, and its only disagreement is the carrier."""
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
    """CASE-1003 gives no defect type at all, and disagrees with the records three ways."""
    facts = facts_for(CASE_1003, SHIPMENT_1003)

    assert facts.shipment_id == "346106093"
    assert facts.damage_type == "Damage due to carrier mishandling"
    assert facts.damage_type_recognised is DamageType.CARRIER_MISHANDLING
    # The description simply does not say how far the damage went. Nothing is
    # invented for it.
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
    """CASE-1004 is the one claim where the damage stopped at the goods."""
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
    """CASE-1005's description agrees with the records on everything but the carrier."""
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


# ---------------------------------------------------------------------------
# The four disagreements
# ---------------------------------------------------------------------------


def test_the_carrier_in_the_description_is_checked_against_the_shipment() -> None:
    """Every sample description that names a carrier names one the shipment does not.

    Four of the five say `Carrier: Other` while the shipment record names a real
    carrier. CASE-1001 is the exception, and only because it names no carrier at
    all — so nothing is compared and nothing is reported.
    """
    disagreement = one(facts_for(CASE_1002, SHIPMENT_1002), ContradictionKind.CARRIER)

    assert disagreement.described == "Other"
    assert disagreement.recorded == "CirroECommerce"
    assert "carrier" in disagreement.why_it_matters

    assert kinds(facts_for(CASE_1001, SHIPMENT_1001)) == ()


def test_a_description_about_a_different_parcel_is_reported() -> None:
    """A shipment id in the prose that is not the case's own shipment is a disagreement.

    No sample claim actually does this — all five quote their own shipment id
    correctly — so the case here is CASE-1001's description on a case pointing at
    a different parcel. It is the disagreement that would matter most if it
    happened, because it means the photographs and the shipment record may be
    about two different journeys.
    """
    facts = facts_for(
        case_payload(shipment_id="344745459"),
        shipment_payload(shipment_id="344745459"),
    )
    disagreement = one(facts, ContradictionKind.SHIPMENT_ID)

    assert facts.shipment_id == "342578703"
    assert disagreement.described == "342578703"
    assert disagreement.recorded == "344745459"


def test_two_affected_orders_on_a_case_that_names_one_order_is_reported() -> None:
    """CASE-1003 claims two affected orders while the case covers a single order."""
    disagreement = one(facts_for(CASE_1003, SHIPMENT_1003), ContradictionKind.AFFECTED_ORDER_COUNT)

    assert disagreement.described == "2 affected orders"
    assert disagreement.recorded == "one order, 337761802"


def test_no_affected_orders_at_all_is_also_a_disagreement() -> None:
    """A count of none is as wrong as a count of two on a case that names one order.

    Nothing here decides which side is right — the point is only that the two
    accounts cannot both be true, and a person is told so (NFR-4).
    """
    facts = facts_from("Shipment ID: 342578703. Number of affected orders: 0.")

    assert facts.affected_order_count == 0
    assert one(facts, ContradictionKind.AFFECTED_ORDER_COUNT).described == "0 affected orders"


def test_the_count_is_not_checked_when_the_case_names_no_order() -> None:
    """With no order on the case there is nothing for the count to disagree with."""
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
    """CASE-1004 says the carrier last scanned the parcel two months after it arrived.

    Both dates are written the same way in the result, so the two can be compared
    without anyone having to translate one of them.
    """
    disagreement = one(facts_for(CASE_1004, SHIPMENT_1004), ContradictionKind.LAST_TRACKING_DATE)

    assert disagreement.described == "2026-03-06"
    assert disagreement.recorded == "2025-12-26"


def test_without_the_shipment_record_the_carrier_and_date_are_read_but_not_checked() -> None:
    """A missing shipment record means two of the four checks cannot run.

    The description is still read in full. What is not reported is silence about
    a check that never happened, which is why the shipment is worth passing in
    whenever it can be read.
    """
    facts = facts_for(CASE_1003)

    assert facts.carrier == "Other"
    assert facts.last_carrier_tracking_date == date(2026, 2, 24)
    assert kinds(facts) == (ContradictionKind.AFFECTED_ORDER_COUNT,)


# ---------------------------------------------------------------------------
# Descriptions that say nothing
# ---------------------------------------------------------------------------


def test_a_case_with_no_description_reads_nothing_and_says_why() -> None:
    """A missing description is an ordinary claim, not a failure (NFR-4).

    Nothing is raised and nothing is guessed. The empty result says in plain
    words that there was nothing to read, so a representative can tell it apart
    from a description that was read and yielded nothing.
    """
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
    """Whitespace is not an account of what happened, and is treated as absent."""
    assert facts_from("   ") == facts_from(None)


def test_a_description_carrying_none_of_the_facts_yields_none_of_them() -> None:
    """A merchant writing in their own words is normal, and produces an empty result.

    Nothing was found and nothing could not be read, so both lists are empty.
    That is a real answer, not a broken one.
    """
    facts = facts_from("The customer rang to say the parcel turned up in a bad way.")

    assert facts.shipment_id is None
    assert facts.damage_type is None
    assert facts.defect_type is None
    assert facts.affected_order_count is None
    assert facts.last_carrier_tracking_date is None
    assert facts.carrier is None
    assert facts.contradictions == ()
    assert facts.unreadable == ()


# ---------------------------------------------------------------------------
# Text written to catch out a careless pattern
# ---------------------------------------------------------------------------


def test_a_product_with_carrier_in_its_name_is_not_mistaken_for_the_carrier() -> None:
    """Only the word "carrier" followed straight by a colon names the carrier.

    Two traps in one description: a product called "Carrier Bag Deluxe", and the
    field name "Date of Last Carrier Tracking", which also contains the word and
    is followed by a date. A pattern that took the first thing after any
    "Carrier" would answer with either "Bag" or "February 22, 2026".
    """
    facts = facts_from(
        "Shipment ID: 342578703. The Carrier Bag Deluxe arrived crushed. "
        "Date of Last Carrier Tracking: February 22, 2026. Carrier: Other."
    )

    assert facts.carrier == "Other"
    assert facts.last_carrier_tracking_date == date(2026, 2, 22)


def test_a_sentence_saying_the_carrier_was_not_at_fault_is_not_read_as_a_cause() -> None:
    """An unlabelled cause is only read when it is the whole sentence.

    "This was not damage due to carrier mishandling" says the opposite of what it
    contains. Reading a cause out of the middle of a sentence would turn a denial
    into an admission, so an unlabelled cause has to start its own sentence.
    """
    facts = facts_from(
        "Shipment ID: 342578703. The customer confirmed this was not damage due to "
        "carrier mishandling."
    )

    assert facts.damage_type is None
    assert facts.damage_type_recognised is None


def test_a_defect_wording_buried_in_a_longer_sentence_is_not_read() -> None:
    """An unlabelled defect is only read when it is the whole sentence, too."""
    facts = facts_from(
        "Shipment ID: 342578703. The customer said both product and shipping box damaged "
        "several other items in the same delivery."
    )

    assert facts.defect_type is None
    assert facts.defect_type_recognised is None


def test_a_labelled_defect_inside_a_longer_sentence_is_still_read() -> None:
    """A field name is a strong enough marker on its own, wherever the sentence goes."""
    facts = facts_from(
        "Shipment ID: 342578703. Defect Type: Product damaged, but shipping box is intact."
    )

    assert facts.defect_type == "Product damaged, but shipping box is intact"
    assert facts.defect_type_recognised is DefectType.PRODUCT_ONLY


def test_a_cause_nobody_has_seen_before_keeps_its_own_words() -> None:
    """An unknown wording is reported as itself rather than filed under the nearest known one.

    The tidy form is left empty, which is what stops a category ShipBob has never
    confirmed from being invented here (FR-1.13).
    """
    facts = facts_from("Shipment ID: 342578703. Damage Type: Damage due to a warehouse forklift.")

    assert facts.damage_type == "Damage due to a warehouse forklift"
    assert facts.damage_type_recognised is None


def test_capitals_and_extra_spacing_do_not_change_what_was_read() -> None:
    """Merchants type field names however they like, and the reading is the same."""
    facts = facts_from(
        "shipment id:  342578703.   DAMAGE TYPE:   Damage due to carrier mishandling.  "
        "carrier:  Royal Mail Tracked 48."
    )

    assert facts.shipment_id == "342578703"
    assert facts.damage_type_recognised is DamageType.CARRIER_MISHANDLING
    # The shipment really was carried by Royal Mail, so nothing disagrees even
    # though the description wrote it in different case from the record.
    assert kinds(facts) == ()


# ---------------------------------------------------------------------------
# Answers that could not be used
# ---------------------------------------------------------------------------


def test_a_description_answering_the_same_field_twice_refuses_to_choose() -> None:
    """Two different shipment ids in one description leaves the shipment id unread.

    Picking one of them would invent the answer, and the two could be two
    different parcels (FR-1.13). Neither is used, and what was written is handed
    to a person instead (NFR-4).
    """
    facts = facts_from("Shipment ID: 342578703. Correction — Shipment ID: 344745459.")

    assert facts.shipment_id is None
    assert kinds(facts) == ()
    assert len(facts.unreadable) == 1
    assert '"342578703", "344745459"' in facts.unreadable[0]


def test_the_same_answer_given_twice_is_not_a_disagreement() -> None:
    """A description repeating itself has still only answered once."""
    facts = facts_from("Shipment ID: 342578703. To confirm, Shipment ID: 342578703.")

    assert facts.shipment_id == "342578703"
    assert facts.unreadable == ()


def test_a_day_that_does_not_exist_is_reported_rather_than_dropped() -> None:
    """30 February is not a date, so no date is taken and the words are handed on."""
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: February 30, 2026.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"February 30, 2026"' in facts.unreadable[0]


def test_a_tracking_date_written_as_something_else_is_reported() -> None:
    """The merchant answered the question, and the answer could not be used.

    Saying so is the difference between a field nobody filled in and a field
    filled in with something unusable, and a representative should be able to
    tell them apart (NFR-4).
    """
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: unknown.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"unknown"' in facts.unreadable[0]


def test_a_count_written_out_in_words_is_left_unread() -> None:
    """Only digits are read as a count; a word is not interpreted as a number."""
    facts = facts_from("Shipment ID: 342578703. Number of affected orders: two.")

    assert facts.affected_order_count is None
    assert facts.unreadable == ()


def test_a_shortened_month_name_is_read() -> None:
    """A month shortened to three letters is the same month, and is read as one."""
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: Feb 22, 2026.")

    assert facts.last_carrier_tracking_date == date(2026, 2, 22)


def test_a_date_written_only_in_numbers_is_not_guessed_at() -> None:
    """11/02/2026 is two different days depending on where it was typed (NFR-1).

    Nothing here can tell which, so no date is taken and the words are passed on
    for a person to settle.
    """
    facts = facts_from("Shipment ID: 342578703. Date of Last Carrier Tracking: 11/02/2026.")

    assert facts.last_carrier_tracking_date is None
    assert len(facts.unreadable) == 1
    assert '"11/02/2026"' in facts.unreadable[0]


def test_the_same_claim_is_read_the_same_way_twice() -> None:
    """Reading a claim twice gives the identical answer, values and order alike (NFR-1)."""
    assert facts_for(CASE_1003, SHIPMENT_1003) == facts_for(CASE_1003, SHIPMENT_1003)
