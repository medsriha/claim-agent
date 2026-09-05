"""Reading a date somebody wrote on a document, including one that could be two dates.

No requirement covers reading a written date. These tests name the nearest ones: the age
limit the reading feeds (FR-0.2), never narrowing two possibilities to one (FR-1.13), and
answering rather than raising for ordinary input (NFR-4).
"""

from __future__ import annotations

from datetime import date

import pytest

from claim_agent.domain.dates import DateReadingKind, read_written_date


def test_case_1001s_email_header_is_settled_by_the_weekday_beside_it() -> None:
    """The real CASE-1001 evidence reads `Wed 11/02/2026`.

    Read day first it is 11 February 2026, which is a Wednesday and agrees with ShipBob's
    own delivery date. Read month first it is 2 November 2026 — a Monday, and a date in the
    future. The weekday the document printed rules one out for free, so nothing is guessed.
    """
    reading = read_written_date("Wed 11/02/2026 16:28", region="US")

    assert reading.preferred == date(2026, 2, 11)
    assert reading.alternative == date(2026, 11, 2)
    assert reading.ruled_out_by_weekday is True
    assert reading.is_ambiguous is False


def test_the_same_date_without_its_weekday_is_ambiguous_either_way() -> None:
    """FR-1.13: with nothing to settle it, both readings are kept and neither is chosen."""
    american = read_written_date("11/02/2026", region="US")
    british = read_written_date("11/02/2026", region="GB")

    assert american.preferred == date(2026, 11, 2)
    assert american.alternative == date(2026, 2, 11)
    assert british.preferred == date(2026, 2, 11)
    assert british.alternative == date(2026, 11, 2)
    assert american.is_ambiguous is True
    assert british.is_ambiguous is True


def test_the_other_reading_is_never_thrown_away() -> None:
    """A caller that only ever saw one reading is the bug this exists to prevent."""
    reading = read_written_date("11/02/2026", region="US")

    assert reading.alternative is not None
    assert "has not been ruled out" in reading.reason


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("25/12/2026", date(2026, 12, 25)),
        ("13/01/2026", date(2026, 1, 13)),
        ("12/25/2026", date(2026, 12, 25)),
    ],
)
def test_a_number_over_twelve_settles_a_slashed_date_on_its_own(
    written: str, expected: date
) -> None:
    """Only one arrangement of it is a real date, so there is nothing to be unsure about."""
    reading = read_written_date(written, region="US")

    assert reading.preferred == expected
    assert reading.is_ambiguous is False
    assert reading.alternative is None


@pytest.mark.parametrize(
    ("written", "expected", "kind"),
    [
        ("2026-02-11", date(2026, 2, 11), DateReadingKind.ISO),
        ("February 22, 2026", date(2026, 2, 22), DateReadingKind.SPELLED_MONTH),
        ("March 6, 2026", date(2026, 3, 6), DateReadingKind.SPELLED_MONTH),
        ("Feb 24 2026", date(2026, 2, 24), DateReadingKind.SPELLED_MONTH),
    ],
)
def test_a_date_that_can_only_be_read_one_way_is_read_that_way(
    written: str, expected: date, kind: DateReadingKind
) -> None:
    """Year-first and spelled-out months are the same date in every country.

    The spelled-out shape is the one ShipBob's own case descriptions use.
    """
    reading = read_written_date(written, region="GB")

    assert reading.preferred == expected
    assert reading.kind is kind
    assert reading.is_ambiguous is False


def test_dashes_are_read_the_same_way_as_slashes() -> None:
    """Documents write the same ambiguous shape both ways."""
    assert read_written_date("11-02-2026", region="GB").preferred == date(2026, 2, 11)


def test_a_weekday_matching_both_readings_settles_nothing() -> None:
    """Only a weekday that eliminates a reading is useful; one that fits both is not.

    Both readings of 01/07/2026 — 1 July and 7 January — fall on a Wednesday, so the
    weekday adds nothing and the date stays ambiguous rather than being called settled.
    """
    assert date(2026, 7, 1).weekday() == date(2026, 1, 7).weekday()

    reading = read_written_date("Wed 01/07/2026", region="US")

    assert reading.is_ambiguous is True
    assert reading.ruled_out_by_weekday is False


def test_a_weekday_that_fits_neither_reading_settles_nothing_either() -> None:
    """A weekday misread off a photograph must not eliminate both readings.

    Neither reading of 11/02/2026 falls on a Friday. Trusting that would leave the date
    with no reading at all, which is worse than leaving it ambiguous.
    """
    reading = read_written_date("Fri 11/02/2026", region="GB")

    assert reading.preferred == date(2026, 2, 11)
    assert reading.alternative == date(2026, 11, 2)
    assert reading.is_ambiguous is True
    assert reading.ruled_out_by_weekday is False


@pytest.mark.parametrize("written", ["", "   ", "no date here", "Standard", "31/02/2026"])
def test_text_that_is_not_a_date_is_answered_rather_than_raised(written: str) -> None:
    """NFR-4: most text on a document is not a date, and that is not a failure."""
    reading = read_written_date(written, region="US")

    assert reading.kind is DateReadingKind.NOT_A_DATE
    assert reading.preferred is None


def test_an_enormous_input_costs_bounded_time() -> None:
    """Text read off a photograph is untrusted and could be any length."""
    assert read_written_date("x" * 100_000, region="US").preferred is None


def test_the_same_text_reads_the_same_way_every_time() -> None:
    """NFR-1: a date that moved between two runs would move the age limit with it."""
    assert read_written_date("Wed 11/02/2026", region="US") == read_written_date(
        "Wed 11/02/2026", region="US"
    )
