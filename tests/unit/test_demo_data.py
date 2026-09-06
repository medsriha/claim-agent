from __future__ import annotations

from tests.fixtures.shipbob import CASE_1001, CONSTRUCTED_REPEAT_MERCHANT_CASE
from tools.shipbob_mock import CASES


def test_two_sample_claims_share_one_merchant() -> None:
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["user_id"] == CASE_1001["user_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["case_id"] != CASE_1001["case_id"]


def test_the_repeat_claim_borrows_the_merchant_and_nothing_else() -> None:
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["order_id"] != CASE_1001["order_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["shipment_id"] != CASE_1001["shipment_id"]


def test_the_repeat_claim_is_served_by_the_stand_in() -> None:
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE in CASES


def test_the_repeat_claim_passes_the_gates_it_needs_to_pass() -> None:
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["sub_category"] == CASE_1001["sub_category"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["description"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["order_id"]
    assert CONSTRUCTED_REPEAT_MERCHANT_CASE["shipment_id"]
