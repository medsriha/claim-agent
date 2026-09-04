"""Where past claims are kept, and how the ones like a new claim are found.

Every damaged product whose claim has been **closed** is written down here, and when a
new one arrives the most similar past ones are read back out (FR-S.1, FR-S.5). It is
the only part of the system that can notice two claims disagreeing.

Nothing still in review is kept. A claim nobody has decided has no outcome, and storing
this system's own untested suggestion would make the store circular.

**Reading happens in two stages, and the split is the whole design.** The database
searches text on its own, so the first stage asks it for records sharing any
meaningful word with the claim in hand. That turns a store of thousands into a
handful without reading them all. The second stage scores that handful carefully,
in Python, using the rules in `claim_agent.domain.precedent` — which are pure, so
the same claim against the same store always comes back with the same records in
the same order (NFR-1).

**No model is involved.** Comparing meaning with one would need another paid
service, another credential and a network call, and would answer slightly
differently on two runs. Word overlap and the shape of the evidence run offline,
cost nothing, and are the same every time. What that costs in accuracy is written
up in DESIGN.md rather than hidden.

Nothing here judges a claim. It stores what an investigation concluded and hands
back what it stored.
"""

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
"""How many records the cheap first stage may hand to the careful second stage.

Bounded so that one very common word cannot pull the whole store into memory. The
database ranks by its own text score before the cut, so the records dropped here
are the ones with the least in common with the claim in hand.
"""


class RetrievedPrecedent(BaseModel):
    """One past claim found to be like the one in hand, and why it was thought so.

    `similarity` carries both the score and the reasons in words, so a
    representative can disagree with the comparison rather than take it on trust
    (FR-S.3).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    record: PrecedentRecord
    similarity: PrecedentSimilarity


class PrecedentSet(BaseModel):
    """What retrieval found for one claim line, including finding nothing.

    Three answers are possible and all three are ordinary (FR-S.13):

    - **Records were found.** `retrieved` holds them, most alike first.
    - **Nothing was similar enough.** `retrieved` is empty and `unavailable_reason`
      is `None`. This is the normal answer for the first claim ever filed, and stays
      normal for an unusual one.
    - **The store could not be read.** `retrieved` is empty and `unavailable_reason`
      says so.

    The last two must never be confused. Telling a representative there is no
    comparable history, when in fact nobody looked, is worse than saying nothing.

    `considered` is how many candidates were scored, which says whether an empty
    answer means "the store holds nothing like this" or "the store holds nothing".
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    retrieved: tuple[RetrievedPrecedent, ...] = ()
    considered: int = 0
    unavailable_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def was_read(self) -> bool:
        """True when the store answered, whether or not it had anything to say.

        Carried in the JSON rather than left for a caller to work out from
        `unavailable_reason` being absent. A client that has to infer "we looked" from
        the absence of a field is one wrong `if` away from telling a representative
        there is no comparable history when nobody actually looked (FR-S.13).
        """
        return self.unavailable_reason is None


class PrecedentStore:
    """Reads and writes the record of claims already investigated.

    Everything lives in the one database file the rest of the service uses, created
    the first time this class is used. Each call opens the file, does its one piece
    of work, and closes it again — the same shape as merchant memory next door, and
    for the same reason: these reads take microseconds and a shared connection
    invites a class of bug that is hard to reproduce.
    """

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file.

        Nothing is read or written here and the file need not exist yet: the first
        call that needs it creates it.

        Args:
            database_path: Where the database file lives, from the settings.
        """
        self._database_path = database_path

    def record(self, precedent: PrecedentRecord) -> None:
        """Write down one closed claim, so a later claim like it can see it (FR-S.1).

        Only closed claims reach here. A line still in review has no outcome, and putting
        this system's own untested suggestion in the store is what would make it circular.

        Writing the same claim line twice replaces its record rather than adding a
        second one. Closing a line again — after a revision — should leave one account of
        that line in the store, not two that disagree.

        The searchable words are rebuilt at the same time and in the same
        transaction, so the index can never describe a record that is no longer
        there.

        Args:
            precedent: What the investigation concluded about one product.

        Raises:
            StorageError: The store could not be written.
        """
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
        """Take a record out of future searches, without destroying it (FR-S.14).

        An approval can be wrong, and once it is precedent it is repeated. This is
        the way back out.

        It withdraws rather than deletes on purpose. The claim's own audit record has
        to survive (NFR-5), and a report that already cited this record should still
        show what that run was actually given. So the record stays, and only stops
        being found.

        Args:
            precedent_id: The record to withdraw.

        Returns:
            True when a record was withdrawn, False when no such record exists.
            Withdrawing an already-withdrawn record succeeds and changes nothing.

        Raises:
            StorageError: The store could not be read or written.
        """
        existing = self.get(precedent_id)
        if existing is None:
            return False
        self.record(existing.model_copy(update={"withdrawn": True}))
        return True

    def get(self, precedent_id: str) -> PrecedentRecord | None:
        """Read back one record by name, or `None` when there is no such record.

        Reads withdrawn records too. Withdrawal takes a record out of *searches*
        (FR-S.14); a caller that names one is asking for that one, and hiding it
        would make a withdrawn record impossible to inspect or put right.

        Args:
            precedent_id: The record to read.

        Raises:
            StorageError: The store could not be read.
        """
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
        """Find the past claims most like this one (FR-S.4, FR-S.5, FR-S.13).

        Two stages. The database is asked for records sharing any meaningful word
        with the claim in hand, which is cheap and narrows the store to a handful.
        Those are then scored properly by the rules in the domain, which compare what
        happened rather than who it happened to.

        Records are ordered by how alike they are; where two are equally alike the more
        recently closed comes first, and then the record's own name, so the order is settled
        rather than left to however the database returned the rows (NFR-1).

        **A store that cannot be read does not stop the claim.** The answer says the
        store could not be read, the investigation carries on without precedent, and
        nothing anywhere mistakes that for a claim with no comparable history
        (FR-S.13, NFR-4). This is the opposite of what merchant memory does, and
        deliberately so: merchant memory has no way to say "unknown", so it has to
        fail loudly instead.

        Args:
            query: The claim about to be investigated, reduced to what gets compared.
            limit: How many records to return at most. A policy value (FR-0.7).
            minimum_similarity: How alike a record must be to come back at all, from
                nothing to one. Also a policy value.
            excluding: A record to leave out — the claim line's own record, when it
                has been investigated before. Without it a re-run would find itself
                and rate itself its own best precedent.

        Returns:
            The records found, most alike first, or an empty set saying which kind of
            empty it is.
        """
        words = query.search_words
        if not words:
            # Nothing to search on. Not a failure: a claim with no description and a
            # product named in digits alone has nothing that could match anything.
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
        """Ask the database for records sharing any meaningful word with the claim.

        The words are joined with OR, so a record needs only one in common to be
        considered — narrowing is all this stage is for, and the careful comparison
        happens afterwards. Each word is quoted, which stops one that happens to be a
        search operator from being read as one.
        """
        initialise(self._database_path)
        match = " OR ".join(f'"{word}"' for word in sorted(words))
        with connect(self._database_path) as connection:
            rows = connection.execute(
                _SELECT_CANDIDATES, (match, excluding or "", _MAX_CANDIDATES)
            ).fetchall()
        return [PrecedentRecord.model_validate_json(row["record"]) for row in rows]

    def _unavailable(self, failure: Exception) -> PrecedentSet:
        """Report a store that could not be read, without failing the claim (FR-S.13).

        Everything that reaches here is logged, because a store nobody can read is a
        fault somebody has to fix, and the answer handed back says only that it could
        not be read — an internal message must never reach a caller.
        """
        logger.error("precedent_store_unavailable", error=str(failure))
        return PrecedentSet(unavailable_reason="The store of past claims could not be read.")

    def _reindex(self, connection: sqlite3.Connection, precedent: PrecedentRecord) -> None:
        """Rebuild one record's searchable words, replacing whatever was there.

        A withdrawn record is left out of the index entirely rather than filtered at
        search time as well. Both would work; leaving it out means a withdrawn record
        costs nothing to skip, and the filter in the query stays as a second guard
        rather than the only one.
        """
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
    """Put the most useful precedent first, and settle every tie (NFR-1).

    Most alike first. Where two are equally alike the more recently closed wins, being the
    better guide to how claims are handled now. The record's own name settles anything left,
    so two runs can never disagree about the order.

    Every record here was decided by a person (FR-S.1), so nothing needs weighing by who
    decided it — they all count the same.

    Sorting is ascending, so each part that should come first is negated here rather than
    the whole list being sorted several times over.
    """
    return (
        -found.similarity.score,
        -found.record.closed_at.timestamp(),
        found.record.precedent_id,
    )


def all_records(database_path: Path) -> Sequence[PrecedentRecord]:
    """Read every record in the store, newest first, withdrawn ones included.

    For a person looking at what is actually in there — a development tool, a test —
    rather than for anything on the claim path, which always goes through
    `similar_to`.

    Args:
        database_path: The database file.

    Raises:
        StorageError: The store could not be read.
    """
    initialise(database_path)
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT record FROM precedent_lines ORDER BY closed_at DESC, precedent_id"
        ).fetchall()
    return [PrecedentRecord.model_validate_json(row["record"]) for row in rows]
