"""That the invented past claims can actually be found, and taken back out (FR-C.8, FR-S.5).

The seeder's whole purpose is that a demonstration finds comparable claims where an empty
store would find none. Nothing about it fails loudly: reword a record, and it still writes
twelve rows, the screen still works, and every claim quietly reports nothing comparable
again. So the test that matters is not that rows were written but that they are *retrieved*
for the sample claims, above the threshold the policy sets.
"""

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
    """One sample claim's own description, which is what precedent is searched on."""
    description = case["description"]
    assert isinstance(description, str)
    return description


def found_for(database_path: Path, description: str) -> list[str]:
    """The past claims a screened claim with this description would be shown.

    Searches the way the screen does — on the merchant's account of the damage and nothing
    else, since no product has been established at that point.
    """
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
    """FR-S.5: invented history that nothing retrieves demonstrates nothing.

    The three sample claims here are the three patterns of damage the seeded records were
    written to echo — a crushed box, carrier mishandling, and a product broken inside an
    intact box. If rewording a record drops it below the policy's threshold, this is what
    says so.
    """
    database_path = a_database(tmp_path)
    seed(database_path)

    assert found_for(database_path, what_the_merchant_said(case)) != []


def test_nothing_is_found_before_the_store_is_seeded(tmp_path: Path) -> None:
    """An empty store finds nothing, which is the honest answer the seeder exists to change."""
    assert found_for(a_database(tmp_path), what_the_merchant_said(CASE_1001)) == []


def test_everything_it_writes_can_be_taken_back_out(tmp_path: Path) -> None:
    """FR-C.8: invented data on screen is indistinguishable from real, so it must be removable."""
    database_path = a_database(tmp_path)
    seed(database_path)
    assert all_records(database_path) != []

    clear(database_path)

    assert all_records(database_path) == []
    # The words a claim is found by live in a second table, and a record deleted without
    # them would leave every search offering claims that are no longer there.
    assert found_for(database_path, what_the_merchant_said(CASE_1001)) == []


def test_seeding_twice_does_not_double_the_history(tmp_path: Path) -> None:
    """The container runs this on every start, not only the first."""
    database_path = a_database(tmp_path)
    seed(database_path)
    seed(database_path)

    assert len(all_records(database_path)) == len(past_claims())


def test_only_if_empty_leaves_an_existing_store_alone(tmp_path: Path) -> None:
    """The guarantee the container relies on: a restart must not touch history already there."""
    database_path = a_database(tmp_path)
    seed(database_path)

    said = seed(database_path, only_if_empty=True)

    assert "Left alone" in said
    assert len(all_records(database_path)) == len(past_claims())


def test_a_cleared_store_is_seeded_again_on_the_next_start(tmp_path: Path) -> None:
    """Clearing the history does not survive a restart, and this is the honest way round.

    `--if-empty` asks whether the store is empty, not whether somebody emptied it on
    purpose. Telling those apart would mean a hidden marker row, and an empty store that
    behaved differently from an empty store is a worse thing to explain than this. Turning
    the seeding off in the container is what stops it for good.
    """
    database_path = a_database(tmp_path)
    seed(database_path)
    clear(database_path)

    seed(database_path, only_if_empty=True)

    assert len(all_records(database_path)) == len(past_claims())


def test_no_invented_claim_was_paid_more_than_the_cap(tmp_path: Path) -> None:
    """FR-1.20: a record showing a payment over the cap would teach the wrong lesson."""
    paid = [one.amount_usd for one in past_claims() if one.amount_usd is not None]

    assert paid != []
    assert all(amount <= CAP_AT_THE_TIME for amount in paid)


def test_one_invented_claim_was_held_down_to_the_cap() -> None:
    """The cap doing something visible is worth demonstrating, so one record shows it."""
    capped = [one for one in past_claims() if one.cap_applied]

    assert len(capped) == 1
    assert capped[0].amount_usd == CAP_AT_THE_TIME


def test_the_outcomes_are_not_all_the_same() -> None:
    """History where every claim was paid tells a representative nothing about judgement."""
    outcomes = {one.outcome for one in past_claims()}

    assert Recommendation.APPROVE in outcomes
    assert Recommendation.REQUEST_INFO in outcomes
    assert len(outcomes) >= 3


def test_a_claim_that_paid_nothing_records_no_amount() -> None:
    """An outcome that paid nothing must not carry a figure, or the store teaches a false one."""
    for one in past_claims():
        if one.outcome in (Recommendation.APPROVE, Recommendation.APPROVE_HIGH_VALUE):
            assert one.amount_usd is not None
        else:
            assert one.amount_usd is None


def test_every_invented_claim_is_priced_in_exact_decimals() -> None:
    """FR-1.21: money is read as text into an exact decimal, never through a float."""
    for one in past_claims():
        assert one.unit_price is None or isinstance(one.unit_price, Decimal)
        assert one.amount_usd is None or isinstance(one.amount_usd, Decimal)
