"""What a support rep has already corrected on a merchant's earlier claims.

When a rep changes something the system recommended — the wrong product picked
out, an amount that should not have been paid — that correction is worth keeping.
The next time the same merchant files a claim, the investigation starts knowing
about it, so the same correction does not have to be made twice (FR-0.5,
FR-3.8). ShipBob has no endpoint that stores this, so the service remembers it
itself.

Merchants are identified by their account number, which never changes, and never
by the brand name shown on the case, which is display text and can be edited
(FR-3.8).

A merchant we have nothing on is the ordinary case, not a problem: a claim from a
merchant who has never needed correcting simply carries no notes.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from claim_agent.domain.models import MerchantCorrection
from claim_agent.storage.database import connect, initialise

_SELECT_FOR_MERCHANT = """
SELECT user_id, case_id, summary, recorded_at
FROM rep_corrections
WHERE user_id = ?
ORDER BY recorded_at, id
"""

_INSERT = """
INSERT INTO rep_corrections (user_id, case_id, summary, recorded_at)
VALUES (?, ?, ?, ?)
"""

_DELETE_ALL = "DELETE FROM rep_corrections"


class MerchantMemory:
    """Reads and writes the corrections held against a merchant.

    Everything is kept in one database file on disk, named by the settings, and
    created the first time this class is used. Each call opens the file, does its
    one piece of work, and closes it again.

    Nothing in this class judges a claim; it stores and returns what a rep
    already decided.
    """

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file.

        Nothing is read or written here, and the file does not have to exist yet:
        building the store is cheap, and the first call that needs the file
        creates it.

        Args:
            database_path: Where the database file lives, from the settings.
        """
        self._database_path = database_path

    def corrections_for(self, user_id: str | None) -> tuple[MerchantCorrection, ...]:
        """Return everything a rep has corrected on this merchant's earlier claims.

        The pre-flight screen calls this while gathering a claim, and passes the
        result on as starting context for the investigation (FR-0.1, FR-0.5).

        Args:
            user_id: The merchant's account number, taken from the case. `None`
                when the case does not name one.

        Returns:
            The corrections, oldest first, and always in that same order — two
            reads of the same claim have to look the same, or the layer stops
            being deterministic (FR-0.6). Corrections written at the very same
            moment come back in the order they were written.

            An empty tuple when the merchant has no corrections, when we have
            never seen them before, and when the case names no merchant at all.
            None of the three is a failure: most claims come from a merchant with
            nothing on file.

        Raises:
            StorageError: The store could not be read. A broken store is not
                allowed to look like a merchant with a clean record (NFR-4).
        """
        if user_id is None:
            return ()

        # Cheap and repeatable, so it runs before every piece of work rather than
        # being something an operator has to remember to do once by hand.
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_FOR_MERCHANT, (user_id,)).fetchall()
        return tuple(_to_correction(row) for row in rows)

    def record_correction(self, correction: MerchantCorrection) -> None:
        """Store one correction a rep made, so the merchant's next claim can see it.

        This is the writing half of FR-3.8. Nothing in the pre-flight screen calls
        it — that screen only reads — and the code that captures a rep's edits
        arrives with the later requirement. It is here now because a store that
        can only be read is not a store: without it there would be no way to put
        anything in, and no way to prove that what comes out is what went in.
        Today its only callers are the tests.

        Args:
            correction: What the rep changed, which merchant it concerns, and
                when. The moment is stored on the UTC clock so that corrections
                written in different places still sort against each other
                correctly.

        Raises:
            StorageError: The store could not be written.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            connection.execute(
                _INSERT,
                (
                    correction.user_id,
                    correction.case_id,
                    correction.summary,
                    _to_stored_text(correction.recorded_at.astimezone(UTC)),
                ),
            )

    def forget_everything(self) -> int:
        """Remove every correction held against every merchant, and say how many went.

        **This exists for demonstrations and for nothing else.** The system is meant never to
        forget what a representative corrected — that is the whole point of the store, and the
        next claim from a merchant is supposed to start knowing it. Somebody showing the system
        needs to start from nothing, though, and doing that by hand means reaching into the
        database, which is worse than a named method that says plainly what it is for.

        There is deliberately no way to remove *one* correction. Choosing which of a
        representative's corrections to forget is a judgement nobody has specified, and an
        interface that allowed it would invite quietly deleting an inconvenient one.

        Returns:
            How many corrections were removed. Zero when there were none, which is ordinary.

        Raises:
            StorageError: The database could not be reached or written.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            return int(connection.execute(_DELETE_ALL).rowcount)


def _to_correction(row: sqlite3.Row) -> MerchantCorrection:
    """Turn one stored row back into a correction.

    The stored moment is text, and reading it back through the claim's own model
    puts it on the UTC clock again, so what comes out names the very same instant
    that went in.

    Args:
        row: One row from the corrections table, readable by column name.
    """
    return MerchantCorrection(
        user_id=row["user_id"],
        case_id=row["case_id"],
        summary=row["summary"],
        recorded_at=row["recorded_at"],
    )


def _to_stored_text(moment: datetime) -> str:
    """Write a moment in time as text the database can sort as well as show.

    Always the same shape, always UTC, always with the fraction of a second
    spelled out even when it is zero. That fixed shape is what lets the ordering
    be done on the text itself: "written first" and "sorts first" then mean the
    same thing, which is what keeps two reads of a merchant's history identical
    (FR-0.6).

    Args:
        moment: A time that already carries a timezone.
    """
    return moment.isoformat(timespec="microseconds")
