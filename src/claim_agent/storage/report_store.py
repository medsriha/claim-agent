from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from claim_agent.report.models import ClaimView, Report
from claim_agent.storage.database import connect, initialise

_UPSERT = """
INSERT INTO reports
    (report_id, version, case_id, stage, state, created_at, record)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (report_id, version) DO UPDATE SET
    case_id = excluded.case_id,
    stage = excluded.stage,
    state = excluded.state,
    created_at = excluded.created_at,
    record = excluded.record
"""

_SELECT_ONE_VERSION = "SELECT record FROM reports WHERE report_id = ? AND version = ?"


_SELECT_LATEST = "SELECT record FROM reports WHERE report_id = ? ORDER BY version DESC LIMIT 1"

_SELECT_VERSIONS = "SELECT record FROM reports WHERE report_id = ? ORDER BY version"


_SELECT_FOR_CASE = """
SELECT record
FROM reports
WHERE case_id = ?
  AND version = (
      SELECT MAX(latest.version) FROM reports AS latest WHERE latest.report_id = reports.report_id
  )
ORDER BY created_at, report_id
"""


class ReportStore:
    """Reads and writes the reports representatives decide from."""

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file."""
        self._database_path = database_path

    def record(self, report: Report) -> None:
        """Write one version of one report down."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            connection.execute(
                _UPSERT,
                (
                    report.report_id,
                    report.version,
                    report.case_id,
                    report.stage.value,
                    report.state.value,
                    report.created_at.isoformat(timespec="microseconds"),
                    report.model_dump_json(),
                ),
            )

    def get(self, report_id: str, *, version: int | None = None) -> Report | None:
        """Read one report, by default the version in force."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            row = (
                connection.execute(_SELECT_LATEST, (report_id,)).fetchone()
                if version is None
                else connection.execute(_SELECT_ONE_VERSION, (report_id, version)).fetchone()
            )
        if row is None:
            return None
        return Report.model_validate_json(row["record"])

    def versions_of(self, report_id: str) -> Sequence[Report]:
        """Every version of one report, oldest first (FR-R.13, NFR-5)."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_VERSIONS, (report_id,)).fetchall()
        return [Report.model_validate_json(row["record"]) for row in rows]

    def for_case(self, case_id: str) -> ClaimView:
        """The claim's report, at the version in force (FR-2.9b)."""
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_FOR_CASE, (case_id,)).fetchall()
        return ClaimView(
            case_id=case_id,
            reports=tuple(Report.model_validate_json(row["record"]) for row in rows),
        )
