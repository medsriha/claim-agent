"""Counting the days between two moments, the way someone reviewing a claim counts them."""

from __future__ import annotations

from datetime import UTC, datetime


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
