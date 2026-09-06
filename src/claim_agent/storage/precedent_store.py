from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field

from claim_agent.domain.precedent import (
    PrecedentQuery,
    PrecedentRecord,
    PrecedentSimilarity,
    meaningful_words,
    similarity,
)
from claim_agent.errors import StorageError
from claim_agent.observability import get_logger
from claim_agent.storage.database import connect, initialise

logger = get_logger(__name__)

_UPSERT = """
INSERT INTO precedent_lines
    (precedent_id, claim_line_id, withdrawn, closed_at, record)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (precedent_id) DO UPDATE SET
    claim_line_id = excluded.claim_line_id,
    withdrawn = excluded.withdrawn,
    closed_at = excluded.closed_at,
    record = excluded.record
"""

_DELETE_SEARCH_WORDS = "DELETE FROM precedent_search WHERE precedent_id = ?"

_INSERT_SEARCH_WORDS = "INSERT INTO precedent_search (precedent_id, words) VALUES (?, ?)"

_SELECT_ONE = "SELECT record FROM precedent_lines WHERE precedent_id = ?"

_SELECT_CANDIDATES = """
SELECT lines.record
FROM precedent_search
JOIN precedent_lines AS lines ON lines.precedent_id = precedent_search.precedent_id
WHERE precedent_search MATCH ?
  AND lines.withdrawn = 0
  AND lines.precedent_id <> ?
ORDER BY bm25(precedent_search), lines.precedent_id
LIMIT ?
"""

_MAX_CANDIDATES = 200
"""How many records the cheap first stage may hand to the careful second stage."""


class RetrievedPrecedent(BaseModel):
    """One past claim found to be like the one in hand, and why it was thought so."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    record: PrecedentRecord
    similarity: PrecedentSimilarity


class PrecedentSet(BaseModel):
    """What retrieval found for one claim line, including finding nothing."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    retrieved: tuple[RetrievedPrecedent, ...] = ()
    considered: int = 0
    unavailable_reason: str | None = None

    @computed_field
    @property
    def was_read(self) -> bool:
        """True when the store answered, whether or not it had anything to say."""
        return self.unavailable_reason is None


class PrecedentStore:
    """Reads and writes the record of claims already investigated."""

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file."""
        self._database_path = database_path

    def record(self, precedent: PrecedentRecord) -> None:
        """Write down one closed claim, so a later claim like it can see it (FR-S.1)."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            connection.execute(
                _UPSERT,
                (
                    precedent.precedent_id,
                    precedent.claim_line_id,
                    int(precedent.withdrawn),
                    precedent.closed_at.isoformat(timespec="microseconds"),
                    precedent.model_dump_json(),
                ),
            )
            self._reindex(connection, precedent)

    def withdraw(self, precedent_id: str) -> bool:
        """Take a record out of future searches, without destroying it (FR-S.14)."""
        existing = self.get(precedent_id)
        if existing is None:
            return False
        self.record(existing.model_copy(update={"withdrawn": True}))
        return True

    def get(self, precedent_id: str) -> PrecedentRecord | None:
        """Read back one record by name, or `None` when there is no such record."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            row = connection.execute(_SELECT_ONE, (precedent_id,)).fetchone()
        if row is None:
            return None
        return PrecedentRecord.model_validate_json(row["record"])

    def similar_to(
        self,
        query: PrecedentQuery,
        *,
        limit: int,
        minimum_similarity: float,
        excluding: str | None = None,
    ) -> PrecedentSet:
        """Find the past claims most like this one (FR-S.4, FR-S.5, FR-S.13)."""
        words = query.search_words
        if not words:
            return PrecedentSet()

        try:
            candidates = self._candidates(words, excluding=excluding)
        except StorageError as failure:
            return self._unavailable(failure)

        scored = [
            RetrievedPrecedent(record=candidate, similarity=similarity(query, candidate))
            for candidate in candidates
        ]
        close_enough = [found for found in scored if found.similarity.score >= minimum_similarity]
        close_enough.sort(key=_ranking)
        return PrecedentSet(
            retrieved=tuple(close_enough[:limit]),
            considered=len(candidates),
        )

    def _candidates(self, words: frozenset[str], *, excluding: str | None) -> list[PrecedentRecord]:
        """Ask the database for records sharing any meaningful word with the claim."""
        initialise(self._database_path)
        match = " OR ".join(f'"{word}"' for word in sorted(words))
        with connect(self._database_path) as connection:
            rows = connection.execute(
                _SELECT_CANDIDATES, (match, excluding or "", _MAX_CANDIDATES)
            ).fetchall()
        return [PrecedentRecord.model_validate_json(row["record"]) for row in rows]

    def _unavailable(self, failure: Exception) -> PrecedentSet:
        """Report a store that could not be read, without failing the claim (FR-S.13)."""
        logger.error("precedent_store_unavailable", error=str(failure))
        return PrecedentSet(unavailable_reason="The store of past claims could not be read.")

    def _reindex(self, connection: sqlite3.Connection, precedent: PrecedentRecord) -> None:
        """Rebuild one record's searchable words, replacing whatever was there."""
        connection.execute(_DELETE_SEARCH_WORDS, (precedent.precedent_id,))
        if precedent.withdrawn:
            return
        words = meaningful_words(precedent.merchant_account) | meaningful_words(
            precedent.product_name
        )
        if not words:
            return
        connection.execute(_INSERT_SEARCH_WORDS, (precedent.precedent_id, " ".join(sorted(words))))


def _ranking(found: RetrievedPrecedent) -> tuple[float, float, str]:
    """Put the most useful precedent first, and settle every tie (NFR-1)."""
    return (
        -found.similarity.score,
        -found.record.closed_at.timestamp(),
        found.record.precedent_id,
    )


def all_records(database_path: Path) -> Sequence[PrecedentRecord]:
    """Read every record in the store, newest first, withdrawn ones included."""
    initialise(database_path)
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT record FROM precedent_lines ORDER BY closed_at DESC, precedent_id"
        ).fetchall()
    return [PrecedentRecord.model_validate_json(row["record"]) for row in rows]
