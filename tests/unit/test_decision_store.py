"""Keeping what representatives decided (FR-C.1).

Nothing in the service writes one of these yet, so these tests are the only thing exercising the
write side, exactly as they are for the store of past claims.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.fixtures.decisions import A_MOMENT, investigated, screened

from claim_agent.errors import StorageError
from claim_agent.storage.decision_store import DecisionStore


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    """A store pointed at a throwaway database that does not exist yet."""
    return DecisionStore(tmp_path / "claims.db")


def test_a_decision_comes_back_as_it_went_in(store: DecisionStore) -> None:
    """Including the fields that are empty on purpose, which are the easy ones to lose."""
    store.record(investigated(rep_words="Logged by phone."))

    [read] = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert read.case_id == "CASE-9001"
    assert read.decided_by is None
    assert read.rep_words == "Logged by phone."
    assert read.recommended.amount_usd == read.decided.amount_usd


def test_a_stopped_claim_records_without_a_recommendation_to_compare(
    store: DecisionStore,
) -> None:
    """FR-C.1: a stopped claim records the same way, with nothing invented to fill a gap."""
    store.record(screened())

    [read] = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert read.stated_confidence is None
    assert read.recommended.outcome is None


def test_writing_the_same_decision_twice_replaces_it_rather_than_counting_it_twice(
    store: DecisionStore,
) -> None:
    """One identifier is one event.

    Two rows carrying the same id would be one review counted twice, and every rate on the
    analysis screen is a count divided by a count.
    """
    store.record(investigated(rep_minutes=8))
    store.record(investigated(rep_minutes=20))

    decisions = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert len(decisions) == 1
    assert decisions[0].rep_minutes == 20


def test_the_end_of_a_window_is_left_out_so_periods_laid_end_to_end_never_overlap(
    store: DecisionStore,
) -> None:
    """A decision on the boundary belongs to the period beginning, not the one ending."""
    store.record(investigated(decided_at=A_MOMENT))

    assert store.decided_between(A_MOMENT, A_MOMENT + timedelta(days=1))
    assert store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT) == []


def test_decisions_come_back_oldest_first_whatever_order_they_went_in(
    store: DecisionStore,
) -> None:
    """The analysis buckets by week, and a stable order is what makes two runs agree (NFR-1)."""
    store.record(investigated(decision_id="b", decided_at=A_MOMENT + timedelta(hours=2)))
    store.record(investigated(decision_id="a", decided_at=A_MOMENT))

    decisions = store.decided_between(A_MOMENT - timedelta(days=1), A_MOMENT + timedelta(days=1))

    assert [one.decision_id for one in decisions] == ["a", "b"]


def test_a_store_nobody_has_written_to_reads_as_empty_rather_than_failing(
    store: DecisionStore,
) -> None:
    """The file is created on first use, so a fresh machine reports nothing rather than an error.

    Nothing decided and a store that cannot be read are different answers, and this is the first
    of the two.
    """
    assert store.decided_between(A_MOMENT, A_MOMENT + timedelta(days=1)) == []
    assert store.count() == 0


def test_clearing_says_how_many_went_so_a_tool_can_report_what_it_undid(
    store: DecisionStore,
) -> None:
    """FR-C.8: invented history has to be removable, and visibly so."""
    store.record(investigated(decision_id="a"))
    store.record(investigated(decision_id="b"))

    assert store.clear() == 2
    assert store.count() == 0


def test_a_database_that_is_not_a_database_fails_loudly_rather_than_looking_empty(
    tmp_path: Path,
) -> None:
    """NFR-4, NFR-6: a broken store must never be mistaken for a quiet month.

    This is the distinction the whole analysis screen rests on, so it is checked at the bottom
    where it starts.
    """
    broken = tmp_path / "not-a-database.db"
    broken.write_text("this is not a database")

    with pytest.raises(StorageError):
        DecisionStore(broken).decided_between(A_MOMENT, datetime.now(UTC))
