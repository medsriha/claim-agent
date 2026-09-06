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
    """Reads and writes the corrections held against a merchant."""

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file."""
        self._database_path = database_path

    def corrections_for(self, user_id: str | None) -> tuple[MerchantCorrection, ...]:
        """Return everything a rep has corrected on this merchant's earlier claims."""
        if user_id is None:
            return ()

        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_FOR_MERCHANT, (user_id,)).fetchall()
        return tuple(_to_correction(row) for row in rows)

    def record_correction(self, correction: MerchantCorrection) -> None:
        """Store one correction a rep made, so the merchant's next claim can see it."""
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
        """Remove every correction held against every merchant, and say how many went."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            return int(connection.execute(_DELETE_ALL).rowcount)


def _to_correction(row: sqlite3.Row) -> MerchantCorrection:
    """Turn one stored row back into a correction."""
    return MerchantCorrection(
        user_id=row["user_id"],
        case_id=row["case_id"],
        summary=row["summary"],
        recorded_at=row["recorded_at"],
    )


def _to_stored_text(moment: datetime) -> str:
    """Write a moment in time as text the database can sort as well as show."""
    return moment.isoformat(timespec="microseconds")
