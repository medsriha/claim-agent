from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from tests.unit.test_report_models import a_report, a_screening_report

from claim_agent.errors import StorageError
from claim_agent.policy import Policy
from claim_agent.report.models import ReportState
from claim_agent.report.review import approve
from claim_agent.storage.database import initialise
from claim_agent.storage.report_store import ReportStore


@pytest.fixture
def store(tmp_path: Path) -> ReportStore:
    return ReportStore(tmp_path / "claims.db")


def table_names(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in rows}


def test_a_report_comes_back_exactly_as_it_was_written(store: ReportStore) -> None:
    written = a_report()
    store.record(written)

    assert store.get(written.report_id) == written


def test_money_survives_being_stored_as_an_exact_amount(store: ReportStore) -> None:
    store.record(a_report(amount_usd=Decimal("0.10")))

    read_back = store.get("RPT-CASE-1001")

    assert read_back is not None
    assert read_back.amount_usd == Decimal("0.10")


def test_a_report_that_does_not_exist_comes_back_as_nothing(store: ReportStore) -> None:
    assert store.get("RPT-NOBODY") is None


def test_the_database_and_its_table_are_made_on_first_use(tmp_path: Path) -> None:
    database = tmp_path / "somewhere" / "new" / "claims.db"
    store = ReportStore(database)
    assert not database.exists()

    assert store.for_case("CASE-1001").reports == ()

    assert database.exists()
    assert "reports" in table_names(database)


def test_preparing_the_database_twice_changes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    initialise(database)
    initialise(database)

    store = ReportStore(database)
    store.record(a_report())
    initialise(database)

    assert store.get("RPT-CASE-1001") == a_report()


def test_writing_a_report_again_replaces_it_rather_than_adding_a_second(
    store: ReportStore,
) -> None:
    store.record(a_report())
    store.record(a_report())

    assert len(store.for_case("CASE-1001").reports) == 1


def test_moving_a_review_on_writes_the_row_again_rather_than_editing_the_report(
    store: ReportStore,
) -> None:
    report = a_report()
    store.record(report)

    approved = approve(
        report,
        policy=Policy(),
        at=report.created_at,
    ).report
    store.record(approved)

    read_back = store.get(report.report_id)
    assert read_back is not None
    assert read_back.state is ReportState.APPROVED
    assert read_back.content == report.content


def test_every_version_of_a_report_is_kept(store: ReportStore) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    versions = store.versions_of("RPT-CASE-1001")

    assert [version.version for version in versions] == [1, 2]


def test_the_version_in_force_is_the_one_that_comes_back_by_default(store: ReportStore) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    latest = store.get("RPT-CASE-1001")

    assert latest is not None
    assert latest.version == 2


def test_an_earlier_version_can_still_be_read_back(store: ReportStore) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    earlier = store.get("RPT-CASE-1001", version=1)

    assert earlier is not None
    assert earlier.version == 1


def test_a_version_that_was_never_written_comes_back_as_nothing(store: ReportStore) -> None:
    store.record(a_report(version=1))

    assert store.get("RPT-CASE-1001", version=9) is None


def test_versions_of_a_report_nobody_wrote_is_empty(store: ReportStore) -> None:
    assert store.versions_of("RPT-NOBODY") == []


def test_fr_2_9b_a_claim_comes_back_as_its_one_report(store: ReportStore) -> None:
    store.record(
        a_report(product_names=("Liposomal Tripeptide Collagen", "Blue Razz Liquid Carnitine"))
    )

    view = store.for_case("CASE-1001")

    assert view.case_id == "CASE-1001"
    assert len(view.reports) == 1
    assert view.reports[0].product_names == (
        "Liposomal Tripeptide Collagen",
        "Blue Razz Liquid Carnitine",
    )


def test_a_claim_shows_its_report_once_however_many_versions_it_has(
    store: ReportStore,
) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    view = store.for_case("CASE-1001")

    assert len(view.reports) == 1
    assert view.reports[0].version == 2


def test_a_claim_nobody_has_asked_about_has_no_reports(store: ReportStore) -> None:
    assert store.for_case("CASE-9999").reports == ()


def test_a_stopped_claim_appears_on_its_claim_like_any_other_report(store: ReportStore) -> None:
    store.record(a_screening_report(case_id="CASE-1004"))

    view = store.for_case("CASE-1004")

    assert len(view.reports) == 1
    assert view.reports[0].product_names == ()


def test_two_reads_of_one_claim_always_agree(store: ReportStore) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    assert store.for_case("CASE-1001") == store.for_case("CASE-1001")


def test_a_file_that_is_not_a_database_is_reported_as_a_handled_failure(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    database.write_bytes(b"this file is not a database")
    store = ReportStore(database)

    with pytest.raises(StorageError) as reading:
        store.for_case("CASE-1001")
    with pytest.raises(StorageError) as writing:
        store.record(a_report())

    assert "sqlite" not in str(reading.value).lower()
    assert "sqlite" not in str(writing.value).lower()

    assert reading.value.code == "storage_unavailable"
    assert reading.value.status_code == 503


def test_a_database_path_that_cannot_be_used_is_reported_as_a_handled_failure(
    tmp_path: Path,
) -> None:
    blocking_file = tmp_path / "not-a-folder"
    blocking_file.write_text("something else lives here")
    store = ReportStore(blocking_file / "claims.db")

    with pytest.raises(StorageError):
        store.get("RPT-CASE-1001")
