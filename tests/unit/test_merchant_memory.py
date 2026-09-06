from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from claim_agent.domain.models import MerchantCorrection
from claim_agent.errors import StorageError
from claim_agent.storage.database import initialise
from claim_agent.storage.merchant_memory import MerchantMemory

BEST_PAW_NUTRITION = "334430"
CLEANBOSS = "283959"

WRITTEN_AT = datetime(2026, 2, 19, 14, 20, 16, 123456, tzinfo=UTC)


def a_correction(**overrides: Any) -> MerchantCorrection:
    fields: dict[str, Any] = {
        "user_id": BEST_PAW_NUTRITION,
        "case_id": "CASE-1001",
        "summary": "Rep paid for the ampoule duo only; the collagen was undamaged.",
        "recorded_at": WRITTEN_AT,
    }
    fields.update(overrides)
    return MerchantCorrection(**fields)


def table_names(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in rows}


def test_a_correction_comes_back_exactly_as_it_was_written(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    written = a_correction()

    memory.record_correction(written)

    assert memory.corrections_for(BEST_PAW_NUTRITION) == (written,)


def test_the_moment_a_correction_was_made_survives_the_round_trip(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")

    memory.record_correction(a_correction(recorded_at=WRITTEN_AT))

    (read_back,) = memory.corrections_for(BEST_PAW_NUTRITION)
    assert read_back.recorded_at == WRITTEN_AT
    assert read_back.recorded_at.microsecond == 123456


def test_a_correction_written_on_another_clock_comes_back_as_the_same_instant(
    tmp_path: Path,
) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    berlin = timezone(timedelta(hours=1))
    written_in_berlin = WRITTEN_AT.astimezone(berlin)

    memory.record_correction(a_correction(recorded_at=written_in_berlin))

    (read_back,) = memory.corrections_for(BEST_PAW_NUTRITION)
    assert read_back.recorded_at == WRITTEN_AT
    assert read_back.recorded_at.utcoffset() == timedelta(0)


def test_corrections_come_back_oldest_first(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    newest = a_correction(case_id="CASE-1006", recorded_at=WRITTEN_AT + timedelta(days=30))
    oldest = a_correction(case_id="CASE-1001", recorded_at=WRITTEN_AT)

    memory.record_correction(newest)
    memory.record_correction(oldest)

    assert memory.corrections_for(BEST_PAW_NUTRITION) == (oldest, newest)


def test_reading_the_same_history_twice_gives_the_same_order(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    first = a_correction(summary="Written first.")
    second = a_correction(summary="Written second.")
    third = a_correction(summary="Written third.")
    for correction in (first, second, third):
        memory.record_correction(correction)

    read_once = memory.corrections_for(BEST_PAW_NUTRITION)
    read_again = memory.corrections_for(BEST_PAW_NUTRITION)

    assert read_once == (first, second, third)
    assert read_again == read_once


def test_one_merchants_corrections_never_reach_another(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    theirs = a_correction(user_id=CLEANBOSS, case_id="CASE-1002")
    ours = a_correction()
    memory.record_correction(theirs)
    memory.record_correction(ours)

    assert memory.corrections_for(BEST_PAW_NUTRITION) == (ours,)
    assert memory.corrections_for(CLEANBOSS) == (theirs,)


def test_a_merchant_we_have_never_seen_has_no_corrections(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    memory.record_correction(a_correction())

    assert memory.corrections_for("999999") == ()


def test_a_case_with_no_merchant_on_it_has_no_corrections(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")

    assert memory.corrections_for(None) == ()


def test_the_database_and_its_table_are_made_on_first_use(tmp_path: Path) -> None:
    database = tmp_path / "somewhere" / "new" / "claims.db"
    memory = MerchantMemory(database)
    assert not database.exists()

    assert memory.corrections_for(BEST_PAW_NUTRITION) == ()

    assert database.exists()
    assert "rep_corrections" in table_names(database)


def test_preparing_the_database_twice_changes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    initialise(database)
    initialise(database)

    memory = MerchantMemory(database)
    memory.record_correction(a_correction())
    initialise(database)

    assert memory.corrections_for(BEST_PAW_NUTRITION) == (a_correction(),)


def test_a_file_that_is_not_a_database_is_reported_as_a_handled_failure(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    database.write_bytes(b"this file is not a database")
    memory = MerchantMemory(database)

    with pytest.raises(StorageError) as reading:
        memory.corrections_for(BEST_PAW_NUTRITION)
    with pytest.raises(StorageError) as writing:
        memory.record_correction(a_correction())

    assert "sqlite" not in str(reading.value).lower()
    assert "sqlite" not in str(writing.value).lower()

    assert reading.value.code == "storage_unavailable"
    assert reading.value.status_code == 503


def test_a_database_path_that_cannot_be_used_is_reported_as_a_handled_failure(
    tmp_path: Path,
) -> None:
    blocking_file = tmp_path / "not-a-folder"
    blocking_file.write_text("something else lives here")
    memory = MerchantMemory(blocking_file / "claims.db")

    with pytest.raises(StorageError):
        memory.corrections_for(BEST_PAW_NUTRITION)


def test_forgetting_everything_empties_the_store_for_every_merchant(tmp_path: Path) -> None:
    memory = MerchantMemory(tmp_path / "claims.db")
    memory.record_correction(a_correction(user_id="334430", case_id="CASE-1001"))
    memory.record_correction(a_correction(user_id="283959", case_id="CASE-1002"))

    forgotten = memory.forget_everything()

    assert forgotten == 2
    assert memory.corrections_for("334430") == ()
    assert memory.corrections_for("283959") == ()


def test_forgetting_an_empty_store_removes_nothing_and_says_so(tmp_path: Path) -> None:
    assert MerchantMemory(tmp_path / "claims.db").forget_everything() == 0
