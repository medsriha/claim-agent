"""Emptying every store at once, so a demonstration starts from nothing (UI-47).

Everything works against a database file in a throwaway directory, so the suite never writes
into the project and no two tests can see each other's data.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.decisions import A_MOMENT, investigated
from tests.unit.test_precedent_store import a_record, search
from tests.unit.test_report_models import a_report

from claim_agent.domain.models import MerchantCorrection
from claim_agent.errors import StorageError
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore
from claim_agent.storage.reset import empty_every_store

BEST_PAW_NUTRITION = "334430"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    """This test's own throwaway database file."""
    return tmp_path / "claims.db"


def fill_every_store(database: Path) -> None:
    """Put one record in each of the four stores, so emptying them has something to remove."""
    MerchantMemory(database).record_correction(
        MerchantCorrection(
            user_id=BEST_PAW_NUTRITION,
            case_id="CASE-1001",
            summary="Rep paid for the ampoule duo only.",
            recorded_at=A_MOMENT,
        )
    )
    ReportStore(database).record(a_report())
    DecisionStore(database).record(investigated())
    PrecedentStore(database).record(a_record())


def test_everything_the_service_remembers_goes_in_one_call(database: Path) -> None:
    """A demonstration starts fresh only if every store starts empty, not just the corrections."""
    fill_every_store(database)

    cleared = empty_every_store(database)

    assert (cleared.corrections, cleared.reports, cleared.decisions, cleared.past_claims) == (
        1,
        1,
        1,
        1,
    )
    assert MerchantMemory(database).corrections_for(BEST_PAW_NUTRITION) == ()
    assert ReportStore(database).get("RPT-CASE-1001") is None
    assert DecisionStore(database).count() == 0
    assert PrecedentStore(database).get("PREC-CASE-0900-L01") is None


def test_every_version_of_a_report_goes_not_only_the_latest(database: Path) -> None:
    """FR-R.13: the back-and-forth *is* the earlier versions, so leaving them is leaving it."""
    reports = ReportStore(database)
    reports.record(a_report(version=1))
    reports.record(a_report(version=2))

    cleared = empty_every_store(database)

    assert cleared.reports == 2
    assert reports.versions_of("RPT-CASE-1001") == []


def test_a_forgotten_past_claim_is_no_longer_found_by_a_search(database: Path) -> None:
    """The words a claim is found by live apart from the claim, and would outlive it."""
    store = PrecedentStore(database)
    store.record(a_record())

    empty_every_store(database)

    assert search(store).retrieved == ()


def test_emptying_a_machine_that_has_never_run_the_service_answers_with_zeroes(
    database: Path,
) -> None:
    """All zeroes is an ordinary answer: there was nothing there, which is not a failure."""
    cleared = empty_every_store(database)

    assert (cleared.corrections, cleared.reports, cleared.decisions, cleared.past_claims) == (
        0,
        0,
        0,
        0,
    )


def test_a_store_that_cannot_be_reached_fails_loudly_and_removes_nothing(tmp_path: Path) -> None:
    """NFR-4: a database that will not open must not read as a system that had nothing in it."""
    blocking_file = tmp_path / "in-the-way"
    blocking_file.write_text("not a directory")

    with pytest.raises(StorageError):
        empty_every_store(blocking_file / "claims.db")
