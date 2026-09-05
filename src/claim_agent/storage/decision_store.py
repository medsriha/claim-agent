"""Every review action a representative has taken, kept so it can be counted later.

A decision is a fact about what a person chose at a moment, so nothing here edits one. Writing
the same decision twice replaces it rather than adding a second copy, which makes an id one
event rather than one row — every rate worked out from this store would be wrong otherwise.

There is one way to remove decisions, and it removes all of them. It exists because a
development tool invents this history and invented history has to be removable (FR-C.8), not
because anything in the service ever needs to forget a decision.

Only one kind of question is ever asked of this store — *what was decided between these two
moments* — because everything built on it reports on a period. So the whole record is kept as
text in one column, with only the moment broken out beside it, and the counting happens in
Python over what comes back. That is the same shape the store of past claims uses, and for the
same reason: nothing needs to search inside a record.

**Nothing in the service writes to this store yet.** The stage where a representative decides is
not built, so on a fresh machine this store is empty and every figure worked out from it is
honestly zero. A development tool fills it with invented history so the screen can be shown
(FR-C.8), and that tool says so in its own words.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from claim_agent.domain.decision import DecisionRecord
from claim_agent.storage.database import connect, initialise

_INSERT = """
INSERT OR REPLACE INTO rep_decisions (decision_id, decided_at, record)
VALUES (?, ?, ?)
"""

# Ordered by the moment, then by the id, so two decisions sharing a moment always come back in
# the same order. Without the tie-break, two runs over the same data could bucket a week
# differently, and a report that changes when nothing changed is worse than no report (NFR-1).
_SELECT_BETWEEN = """
SELECT record
FROM rep_decisions
WHERE decided_at >= ? AND decided_at < ?
ORDER BY decided_at, decision_id
"""

_DELETE_ALL = "DELETE FROM rep_decisions"

_COUNT = "SELECT COUNT(*) AS total FROM rep_decisions"


class DecisionStore:
    """Reads and writes what representatives decided.

    Everything is kept in the one database file on disk named by the settings, created the first
    time this class is used. Each call opens the file, does its one piece of work, and closes it
    again.

    Nothing in this class judges a claim or works out a figure. It stores decisions and hands
    them back; what they add up to is decided next door, where it can be tested without a
    database.
    """

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file.

        Nothing is read or written here, and the file does not have to exist yet: building the
        store is cheap, and the first call that needs the file creates it.

        Args:
            database_path: Where the database file lives, from the settings.
        """
        self._database_path = database_path

    def record(self, decision: DecisionRecord) -> None:
        """Write down one review action.

        Writing the same decision twice replaces the first copy rather than adding a second.
        A decision is identified by its own id, so two rows carrying that id would be the same
        event counted twice, and every rate worked out from this store would be wrong. This is
        the opposite of the choice merchant memory makes, where a representative really might
        correct the same thing twice and both corrections matter.

        Args:
            decision: What was decided, and how it differed from the advice.

        Raises:
            StorageError: The database could not be reached or written.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            connection.execute(
                _INSERT,
                (
                    decision.decision_id,
                    decision.decided_at.isoformat(),
                    decision.model_dump_json(),
                ),
            )

    def decided_between(self, start: datetime, end: datetime) -> Sequence[DecisionRecord]:
        """Every decision taken from `start` up to but not including `end`.

        The end is excluded so that periods laid end to end cover every moment exactly once. A
        decision taken at midnight belongs to the day beginning, not the one ending, and nothing
        is counted in two periods.

        Args:
            start: The first moment to include, in UTC.
            end: The first moment to leave out, in UTC.

        Returns:
            The decisions, oldest first. An empty sequence means nobody decided anything in that
            stretch of time, which is an ordinary answer and not a failure — the caller is
            responsible for not reporting it as an outage.

        Raises:
            StorageError: The database could not be reached or read.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(
                _SELECT_BETWEEN, (start.isoformat(), end.isoformat())
            ).fetchall()
        return [DecisionRecord.model_validate_json(row["record"]) for row in rows]

    def count(self) -> int:
        """How many decisions are held altogether.

        Used to tell "this period is empty" from "this store is empty", which read the same on a
        screen and mean very different things: the first is a quiet month, the second is a system
        nobody has used yet.

        Raises:
            StorageError: The database could not be reached or read.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            row = connection.execute(_COUNT).fetchone()
        total: int = row["total"]
        return total

    def clear(self) -> int:
        """Remove every decision, and say how many went.

        Here for one reason: a development tool invents this history, and invented history on a
        screen is indistinguishable from the real thing, so there has to be an obvious way to
        take it back out again (FR-C.8). Nothing in the service calls this.

        Returns:
            How many decisions were removed.

        Raises:
            StorageError: The database could not be reached or written.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            return int(connection.execute(_DELETE_ALL).rowcount)
