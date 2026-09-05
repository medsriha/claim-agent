"""Counting days between two moments, and reading a date somebody wrote down.

Two jobs, and they sit together because both are about turning a date into something a
claim can be judged on.

Counting the days is the older of the two and answers the age limit (FR-0.2). Reading a
written date is newer and answers no requirement at all: it exists because one sample
claim's evidence carries the email header `Wed 11/02/2026`, which is 11 February to most
of the world and 2 November in the United States. The age limit is measured from a date
like that one, so the reading you take decides the answer. See `read_written_date`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

_MAX_DATE_TEXT: Final = 200
"""How much text is scanned for a date.

Text read off a photograph is untrusted and could be any length. A date is never two
hundred characters long, and cutting the rest off costs nothing.
"""

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

# `2026-02-11`. Year first, so there is nothing to settle.
_ISO_PATTERN: Final = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")

# `February 22, 2026` and `Feb 22 2026` — the shape ShipBob's own case descriptions use.
_SPELLED_PATTERN: Final = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b"
)

# `11/02/2026` and `11-02-2026`. The shape that can mean two different days.
_SLASHED_PATTERN: Final = re.compile(
    r"\b(?P<first>\d{1,2})[/-](?P<second>\d{1,2})[/-](?P<year>\d{4})\b"
)

# A weekday written beside the date, as in `Wed 11/02/2026`. Free evidence.
_WEEKDAY_PATTERN: Final = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.IGNORECASE)


def whole_days_between(earlier: datetime, later: datetime) -> int:
    """Count whole calendar days from one moment to the other, on the UTC clock.

    This is how long a merchant waited before filing: delivery goes in, the
    moment the case was opened goes in, and the number that comes out decides
    whether the claim is too old to reimburse (FR-0.2).

    Calendar days, not elapsed twenty-four hour stretches. A parcel delivered at
    23:59 and a claim filed two minutes later, after midnight, counts as one day
    apart, because that is how a person reading the two dates would count it.
    Both moments are moved to UTC first, so a claim is counted the same way
    wherever the two dates were originally written (FR-0.6).

    The result is negative when `later` is in fact the earlier of the two — a
    case created before its own delivery date, which does happen in real data.
    That is handed back as it is rather than hidden, because deciding what a
    negative age means is a judgement, not arithmetic.

    Raises `ValueError` if either moment arrives without a timezone. A time with
    no timezone would be read as the clock of whichever machine happens to run
    this, so the same case could be judged differently in two places, and the
    promise that the pre-flight screen is deterministic would quietly break
    (FR-0.6).
    """
    if earlier.utcoffset() is None or later.utcoffset() is None:
        raise ValueError("Both moments need a timezone before their days apart can be counted.")
    return (later.astimezone(UTC).date() - earlier.astimezone(UTC).date()).days


class DateReadingKind(StrEnum):
    """How a written date was laid out, which is what decides whether it is ambiguous.

    `ISO` and `SPELLED_MONTH` can only be read one way. `SLASHED` is the troublesome one:
    `11/02/2026` is 11 February to most of the world and 2 November in the United States,
    and nothing inside the text itself settles which.
    """

    ISO = "iso"
    SPELLED_MONTH = "spelled_month"
    SLASHED = "slashed"
    NOT_A_DATE = "not_a_date"


class WrittenDate(BaseModel):
    """A date read off a document, with every reading it could honestly have.

    Attributes:
        text: What was read, exactly as it appeared.
        kind: How it was laid out.
        preferred: The reading the region asks for, or the only possible one. `None` when
            the text is not a date at all.
        alternative: The other reading of an ambiguous date. **Never thrown away**, even
            though `preferred` is the one a caller will usually take — a caller that
            silently took one reading of `11/02/2026` and never saw the other is the bug
            this exists to prevent.
        is_ambiguous: True when both readings are real dates and nothing ruled one out.
        ruled_out_by_weekday: True when the text named a weekday and that weekday
            eliminated one of the two readings. This is the happy case: it settles an
            ambiguous date without anybody guessing.
        reason: One plain sentence a representative can agree or disagree with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    kind: DateReadingKind
    preferred: date | None = None
    alternative: date | None = None
    is_ambiguous: bool = False
    ruled_out_by_weekday: bool = False
    reason: str


def read_written_date(text: str, *, region: str) -> WrittenDate:
    """Read a date off a document, keeping every reading it could honestly have.

    Documents a merchant photographs write dates however their software felt like it. Most
    of those are unambiguous and this simply reads them. One shape is not: a date written
    with slashes or dashes where both halves are twelve or under can be read two ways, and
    the two can be months apart.

    **This is not a theoretical problem.** One sample claim's evidence carries the email
    header `Wed 11/02/2026`. Read day-first that is 11 February 2026, which agrees with
    ShipBob's own delivery date and with a parcel that went by Royal Mail. Read month-first
    it is 2 November 2026 — a date in the future. The age limit on a claim (FR-0.2) is
    measured from a date like this one, so which reading you take decides whether the claim
    is inside it.

    Three things happen, in order:

    1. **A named weekday settles it for free.** `Wed` is a fact the document itself
       supplies. 11 February 2026 was a Wednesday and 2 November 2026 was a Monday, so the
       weekday eliminates one reading without anybody having to guess. When a weekday is
       present and matches exactly one reading, the date is no longer ambiguous.
    2. **Otherwise the region breaks the tie, and both readings are kept.** The region's
       reading becomes `preferred`, and the other stays on `alternative` where a caller
       cannot miss it.
    3. **A date that can only be read one way is answered plainly**, with nothing on
       `alternative` and `is_ambiguous` false.

    Args:
        text: The date as the document wrote it, optionally with a weekday in front.
        region: `"GB"` to read the day first, anything else to read the month first. This
            comes from `policy.default_date_region`, so the default is a setting rather
            than a number buried here (FR-0.7, NFR-7).

    Returns:
        Every reading the text honestly supports. Text that is not a date comes back saying
        so rather than raising: most text on a document is not a date (NFR-4).
    """
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
    """Read `February 22, 2026`, the shape ShipBob's own case descriptions use.

    A spelled-out month cannot be confused with a day, so there is nothing to settle.
    """
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

    # One half over twelve leaves only one arrangement that is a real date, which is what
    # makes such a date unambiguous. Written as two separate checks rather than one so the
    # reader — and the type checker — can see that both readings survive past here.
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
    """The weekday named in the text, as Monday-is-zero, or `None` if none is named.

    A weekday on a document is a free fact: it was printed by the system that knew the real
    date, so it can eliminate a reading that nothing else could.
    """
    found = _WEEKDAY_PATTERN.search(text)
    return None if found is None else _WEEKDAYS[found[1][:3].lower()]


def _date_or_none(year: int, month: int, day: int) -> date | None:
    """Build a date, answering `None` for an arrangement that is not a real one.

    `None` is how a month of 13 or a 31st of February is rejected, which is exactly what
    makes a date with a number over twelve in it unambiguous.
    """
    try:
        return date(year, month, day)
    except ValueError:
        return None
