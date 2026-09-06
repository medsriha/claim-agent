from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from claim_agent.storage.database import connect, initialise

_DELETE_CORRECTIONS = "DELETE FROM rep_corrections"

_DELETE_REPORTS = "DELETE FROM reports"

_DELETE_DECISIONS = "DELETE FROM rep_decisions"

_DELETE_PAST_CLAIMS = "DELETE FROM precedent_lines"


_DELETE_SEARCH_INDEX = "DELETE FROM precedent_search"


class ClearedStores(BaseModel):
    """How many records went from each store."""

    corrections: int
    reports: int
    decisions: int
    past_claims: int


def empty_every_store(database_path: Path) -> ClearedStores:
    """Throw away everything the service has remembered, and say how much went."""
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
