from __future__ import annotations

from tests.fixtures.shipbob import CASE_1001, CONSTRUCTED_REPEAT_MERCHANT_CASE
from tools.shipbob_mock import CASES


def test_two_sample_claims_share_one_merchant() -> None:
    """FR-C.8: showing carry-forward needs a second claim from a merchant who already has one."""
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["user_id"] == CASE_1001["user_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["case_id"] != CASE_1001["case_id"]


def test_the_repeat_claim_borrows_the_merchant_and_nothing_else() -> None:
    """What carries across must be the merchant, not the claim.

    Sharing an order or a parcel would make the second claim a copy of the first, and a
    correction appearing on it would prove nothing about merchants — only that the same claim
    looks like itself.
    """
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["order_id"] != CASE_1001["order_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["shipment_id"] != CASE_1001["shipment_id"]


def test_the_repeat_claim_is_served_by_the_stand_in() -> None:
    """A constructed claim nobody can open demonstrates nothing."""
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE in CASES


def test_the_repeat_claim_passes_the_gates_it_needs_to_pass() -> None:
    """It has to be investigated for a correction to reach an investigation.

    The other constructed claims exist to be turned away by pre-flight. This one is the
    opposite, so the fields the gates read are checked here rather than left to chance
    (FR-0.2).
    """
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["sub_category"] == CASE_1001["sub_category"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["description"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["order_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["shipment_id"]
