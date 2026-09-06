from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.fixtures.decisions import A_MOMENT, investigated, screened

from claim_agent.errors import StorageError
from claim_agent.storage.decision_store import DecisionStore


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    return DecisionStore(tmp_path / "claims.db")


def test_a_decision_comes_back_as_it_went_in(store: DecisionStore) -> None:
    store.record(investigated(rep_words="Logged by phone."))

    [read] = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert read.case_id == "CASE-9001"
    assert read.decided_by is None
    assert read.rep_words == "Logged by phone."
    assert read.recommended.amount_usd == read.decided.amount_usd


def test_a_stopped_claim_records_without_a_recommendation_to_compare(
    store: DecisionStore,
) -> None:
    store.record(screened())

    [read] = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert read.stated_confidence is None
    assert read.recommended.outcome is None


def test_writing_the_same_decision_twice_replaces_it_rather_than_counting_it_twice(
    store: DecisionStore,
) -> None:
    store.record(investigated(rep_minutes=8))
    store.record(investigated(rep_minutes=20))

    decisions = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert len(decisions) == 1
    assert decisions[0].rep_minutes == 20


def test_the_end_of_a_window_is_left_out_so_periods_laid_end_to_end_never_overlap(
    store: DecisionStore,
) -> None:
    store.record(investigated(decided_at=A_MOMENT))

    assert store.decided_between(A_MOMENT, A_MOMENT + timedelta(days=1))
    assert store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT) == []


def test_decisions_come_back_oldest_first_whatever_order_they_went_in(
    store: DecisionStore,
) -> None:
    store.record(investigated(decision_id="b", decided_at=A_MOMENT + timedelta(hours=2)))
    store.record(investigated(decision_id="a", decided_at=A_MOMENT))

    decisions = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert [one.decision_id for one in decisions] == ["a", "b"]


def test_a_store_nobody_has_written_to_reads_as_empty_rather_than_failing(
    store: DecisionStore,
) -> None:
    assert store.decided_between(A_MOMENT, A_MOMENT + timedelta(days=1)) == []
    assert store.count() == 0


def test_clearing_says_how_many_went_so_a_tool_can_report_what_it_undid(
    store: DecisionStore,
) -> None:
    store.record(investigated(decision_id="a"))
    store.record(investigated(decision_id="b"))

    assert store.clear() == 2
    assert store.count() == 0


def test_a_database_that_is_not_a_database_fails_loudly_rather_than_looking_empty(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "not-a-database.db"
    broken.write_text("this is not a database")

    with pytest.raises(StorageError):
        DecisionStore(broken).decided_between(A_MOMENT, datetime.now(UTC))
