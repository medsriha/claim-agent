from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.shipbob import CASE_1001, CASE_1003, CASE_1004
from tools.seed_precedents import CAP_AT_THE_TIME, clear, past_claims, seed

from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentQuery
from claim_agent.policy import Policy
from claim_agent.storage.precedent_store import PrecedentStore, all_records


def a_database(tmp_path: Path) -> Path:
    return tmp_path / "claims.db"


def what_the_merchant_said(case: dict[str, object]) -> str:
    description = case["description"]
    assert isinstance(description, str)
    return description


def found_for(database_path: Path, description: str) -> list[str]:
    policy = Policy()
    store = PrecedentStore(database_path)
    result = store.similar_to(
        PrecedentQuery(
            merchant_account=description,
            product_name="",
            unit_price=None,
            match=MatchOutcome.MATCHED,
        ),
        limit=policy.precedent_results_per_product,
        minimum_similarity=policy.min_precedent_similarity,
    )
    return [one.record.case_id for one in result.retrieved]


@pytest.mark.parametrize("case", [CASE_1001, CASE_1003, CASE_1004])
def test_a_sample_claim_finds_comparable_past_claims(
    tmp_path: Path, case: dict[str, object]
) -> None:
    database_path = a_database(tmp_path)
    seed(database_path)

    assert found_for(database_path, what_the_merchant_said(case)) != []


def test_nothing_is_found_before_the_store_is_seeded(tmp_path: Path) -> None:
    assert found_for(a_database(tmp_path), what_the_merchant_said(CASE_1001)) == []


def test_everything_it_writes_can_be_taken_back_out(tmp_path: Path) -> None:
    database_path = a_database(tmp_path)
    seed(database_path)
    assert all_records(database_path) != []

    clear(database_path)

    assert all_records(database_path) == []
    assert found_for(database_path, what_the_merchant_said(CASE_1001)) == []


def test_seeding_twice_does_not_double_the_history(tmp_path: Path) -> None:
    database_path = a_database(tmp_path)
    seed(database_path)
    seed(database_path)

    assert len(all_records(database_path)) == len(past_claims())


def test_only_if_empty_leaves_an_existing_store_alone(tmp_path: Path) -> None:
    database_path = a_database(tmp_path)
    seed(database_path)

    said = seed(database_path, only_if_empty=True)

    assert "Left alone" in said
    assert len(all_records(database_path)) == len(past_claims())


def test_a_cleared_store_is_seeded_again_on_the_next_start(tmp_path: Path) -> None:
    database_path = a_database(tmp_path)
    seed(database_path)
    clear(database_path)

    seed(database_path, only_if_empty=True)

    assert len(all_records(database_path)) == len(past_claims())


def test_no_invented_claim_was_paid_more_than_the_cap(tmp_path: Path) -> None:
    paid = [one.amount_usd for one in past_claims() if one.amount_usd is not None]

    assert paid != []
    assert all(amount <= CAP_AT_THE_TIME for amount in paid)


def test_one_invented_claim_was_held_down_to_the_cap() -> None:
    capped = [one for one in past_claims() if one.cap_applied]

    assert len(capped) == 1
    assert capped[0].amount_usd == CAP_AT_THE_TIME


def test_the_outcomes_are_not_all_the_same() -> None:
    outcomes = {one.outcome for one in past_claims()}

    assert Recommendation.APPROVE in outcomes
    assert Recommendation.REQUEST_INFO in outcomes
    assert len(outcomes) >= 3


def test_a_claim_that_paid_nothing_records_no_amount() -> None:
    for one in past_claims():
        if one.outcome in (Recommendation.APPROVE, Recommendation.APPROVE_HIGH_VALUE):
            assert one.amount_usd is not None
        else:
            assert one.amount_usd is None


def test_every_invented_claim_is_priced_in_exact_decimals() -> None:
    for one in past_claims():
        assert one.unit_price is None or isinstance(one.unit_price, Decimal)
        assert one.amount_usd is None or isinstance(one.amount_usd, Decimal)
