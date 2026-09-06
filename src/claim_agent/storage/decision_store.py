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


_SELECT_BETWEEN = """
SELECT record
FROM rep_decisions
WHERE decided_at >= ? AND decided_at < ?
ORDER BY decided_at, decision_id
"""

_DELETE_ALL = "DELETE FROM rep_decisions"

_COUNT = "SELECT COUNT(*) AS total FROM rep_decisions"


class DecisionStore:
    """Reads and writes what representatives decided."""

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file."""
        self._database_path = database_path

    def record(self, decision: DecisionRecord) -> None:
        """Write down one review action."""
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
        """Every decision taken from `start` up to but not including `end`."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(
                _SELECT_BETWEEN, (start.isoformat(), end.isoformat())
            ).fetchall()
        return [DecisionRecord.model_validate_json(row["record"]) for row in rows]

    def count(self) -> int:
        """How many decisions are held altogether."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            row = connection.execute(_COUNT).fetchone()
        total: int = row["total"]
        return total

    def clear(self) -> int:
        """Remove every decision, and say how many went."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            return int(connection.execute(_DELETE_ALL).rowcount)
