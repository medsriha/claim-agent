from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from claim_agent.storage.database import connect, initialise

_DELETE_CORRECTIONS = "DELETE FROM rep_corrections"

_DELETE_REPORTS = "DELETE FROM reports"

_DELETE_DECISIONS = "DELETE FROM rep_decisions"

_DELETE_PAST_CLAIMS = "DELETE FROM precedent_lines"

# The words a past claim is found by are kept in a separate search index, and emptying the
# claims does not empty it. Left behind, the index would go on offering claims that are no
# longer there, and every search would come back with nothing found for records it says exist.
_DELETE_SEARCH_INDEX = "DELETE FROM precedent_search"


class ClearedStores(BaseModel):
    """How many records went from each store.

    Counts rather than nothing at all, because "it worked" and "there was nothing there" look
    identical on a screen otherwise, and somebody clearing a machine before a demonstration
    wants to know which of the two happened.
    """

    corrections: int
    reports: int
    decisions: int
    past_claims: int


def empty_every_store(database_path: Path) -> ClearedStores:
    """Throw away everything the service has remembered, and say how much went.

    **This destroys real history and there is no undo.** It exists so that a demonstration can
    start from nothing: what representatives corrected for each merchant, every report and every
    earlier version of one, what representatives decided, and the past closed claims a new claim
    is priced against. Emptying only the corrections is not enough — a claim already investigated
    keeps its report, and opening it again shows the whole back-and-forth still there.

    Everything goes in one write, so a failure halfway cannot leave reports gone but the
    decisions about them still standing.

    Args:
        database_path: The database file, from the settings. It is created if absent, which is
            why clearing a machine that has never run the service answers with zeroes rather
            than failing.

    Returns:
        How many records went from each store. All zeroes is an ordinary answer.

    Raises:
        StorageError: The database could not be reached or written. Nothing was removed.
    """
    initialise(database_path)
    with connect(database_path) as connection:
        corrections = connection.execute(_DELETE_CORRECTIONS).rowcount
        reports = connection.execute(_DELETE_REPORTS).rowcount
        decisions = connection.execute(_DELETE_DECISIONS).rowcount
        past_claims = connection.execute(_DELETE_PAST_CLAIMS).rowcount
        connection.execute(_DELETE_SEARCH_INDEX)
    return ClearedStores(
        corrections=int(corrections),
        reports=int(reports),
        decisions=int(decisions),
        past_claims=int(past_claims),
    )
