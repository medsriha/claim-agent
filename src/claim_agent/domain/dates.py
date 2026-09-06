from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

_MAX_DATE_TEXT: Final = 200
"""How much text is scanned for a date."""

_MONTHS: Final = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
"""Month names by their first three letters, so `February` and `Feb` read the same."""

_WEEKDAYS: Final = {
    name: number for number, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
}
"""Weekday names by their first three letters, numbered the way Python numbers them."""


_ISO_PATTERN: Final = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")


_SPELLED_PATTERN: Final = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b"
)


_SLASHED_PATTERN: Final = re.compile(
    r"\b(?P<first>\d{1,2})[/-](?P<second>\d{1,2})[/-](?P<year>\d{4})\b"
)


_WEEKDAY_PATTERN: Final = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.IGNORECASE)


def whole_days_between(earlier: datetime, later: datetime) -> int:
    """Count whole calendar days from one moment to the other, on the UTC clock."""
    if earlier.utcoffset() is None or later.utcoffset() is None:
        raise ValueError("Both moments need a timezone before their days apart can be counted.")
    return (later.astimezone(UTC).date() - earlier.astimezone(UTC).date()).days


class DateReadingKind(StrEnum):
    """How a written date was laid out, which is what decides whether it is ambiguous."""

    ISO = "iso"
    SPELLED_MONTH = "spelled_month"
    SLASHED = "slashed"
    NOT_A_DATE = "not_a_date"


class WrittenDate(BaseModel):
    """A date read off a document, with every reading it could honestly have."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    kind: DateReadingKind
    preferred: date | None = None
    alternative: date | None = None
    is_ambiguous: bool = False
    ruled_out_by_weekday: bool = False
    reason: str


def read_written_date(text: str, *, region: str) -> WrittenDate:
    """Read a date off a document, keeping every reading it could honestly have."""
    tidied = " ".join(text[:_MAX_DATE_TEXT].split())
    if not tidied:
        return WrittenDate(
            text=text, kind=DateReadingKind.NOT_A_DATE, reason="There is no date in this text."
        )

    for read in (_read_iso, _read_spelled_month):
        found = read(tidied)
        if found is not None:
            return found

    return _read_slashed(tidied, region=region) or WrittenDate(
        text=tidied,
        kind=DateReadingKind.NOT_A_DATE,
        reason=f"No date could be read from {tidied!r}.",
    )


def _read_iso(text: str) -> WrittenDate | None:
    """Read `2026-02-11`, which every country reads the same way."""
    found = _ISO_PATTERN.search(text)
    if found is None:
        return None
    only = _date_or_none(int(found["year"]), int(found["month"]), int(found["day"]))
    if only is None:
        return None
    return WrittenDate(
        text=text,
        kind=DateReadingKind.ISO,
        preferred=only,
        reason=f"{found[0]} is written year first, so it can only mean {only.isoformat()}.",
    )


def _read_spelled_month(text: str) -> WrittenDate | None:
    """Read `February 22, 2026`, the shape ShipBob's own case descriptions use."""
    found = _SPELLED_PATTERN.search(text)
    if found is None:
        return None
    month = _MONTHS.get(found["month"][:3].lower())
    if month is None:
        return None
    only = _date_or_none(int(found["year"]), month, int(found["day"]))
    if only is None:
        return None
    return WrittenDate(
        text=text,
        kind=DateReadingKind.SPELLED_MONTH,
        preferred=only,
        reason=f"{found[0]} names its month in words, so it can only mean {only.isoformat()}.",
    )


def _read_slashed(text: str, *, region: str) -> WrittenDate | None:
    """Read `11/02/2026` or `11-02-2026`, which is the shape that can mean two things."""
    found = _SLASHED_PATTERN.search(text)
    if found is None:
        return None

    first, second, year = int(found["first"]), int(found["second"]), int(found["year"])
    day_first = _date_or_none(year, second, first)
    month_first = _date_or_none(year, first, second)

    if day_first is not None and month_first is None:
        return _the_only_reading(text, found[0], day_first)
    if month_first is not None and day_first is None:
        return _the_only_reading(text, found[0], month_first)
    if day_first is None or month_first is None:
        return None

    weekday = _weekday_in(text)
    if weekday is not None:
        matches = [one for one in (day_first, month_first) if one.weekday() == weekday]
        if len(matches) == 1:
            settled = matches[0]
            other = month_first if settled == day_first else day_first
            return WrittenDate(
                text=text,
                kind=DateReadingKind.SLASHED,
                preferred=settled,
                alternative=other,
                ruled_out_by_weekday=True,
                reason=(
                    f"{found[0]} could be {day_first.isoformat()} or "
                    f"{month_first.isoformat()}, but the day of the week written beside it "
                    f"only fits {settled.isoformat()}."
                ),
            )

    reads_day_first = region.strip().upper() == "GB"
    preferred = day_first if reads_day_first else month_first
    alternative = month_first if reads_day_first else day_first
    return WrittenDate(
        text=text,
        kind=DateReadingKind.SLASHED,
        preferred=preferred,
        alternative=alternative,
        is_ambiguous=True,
        reason=(
            f"{found[0]} could be {day_first.isoformat()} or {month_first.isoformat()}, and "
            f"nothing in the text settles it. Read as {region.strip().upper()} it is "
            f"{preferred.isoformat()}, but the other reading has not been ruled out."
        ),
    )


def _the_only_reading(text: str, written: str, only: date) -> WrittenDate:
    """Answer a slashed date that has just one real reading, because a half is over twelve."""
    return WrittenDate(
        text=text,
        kind=DateReadingKind.SLASHED,
        preferred=only,
        reason=(
            f"{written} has a number over twelve in it, so it can only mean {only.isoformat()}."
        ),
    )


def _weekday_in(text: str) -> int | None:
    """The weekday named in the text, as Monday-is-zero, or `None` if none is named."""
    found = _WEEKDAY_PATTERN.search(text)
    return None if found is None else _WEEKDAYS[found[1][:3].lower()]


def _date_or_none(year: int, month: int, day: int) -> date | None:
    """Build a date, answering `None` for an arrangement that is not a real one."""
    try:
        return date(year, month, day)
    except ValueError:
        return None
