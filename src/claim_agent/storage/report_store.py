"""The reports representatives decide from, kept so they can be fetched back.

Until this store existed, everything an investigation established lived only in the reply to the
request that asked for it: close the page and it was gone, and there was nothing for a
representative to approve later or for anyone to audit afterwards (NFR-3, NFR-5).

**A report keeps every version of itself.** `report_id` names a report and `(report_id, version)`
names one telling of it, because reworking a report around a representative's feedback has to
leave the version they were looking at intact (FR-R.13). That stage is not built, so every report
here is version 1 today — which is exactly why every read that does not name a version has to ask
for the highest one rather than assuming there is only one.

**Only one thing about a stored report ever changes**, and that is where its review has got to. It
changes by writing the row again with a new copy of the report, never by editing what the report
says. A report is the account of something that already happened; the account of who changed its
state lives in the record of decisions next door.

**This store fails loudly.** A claim whose reports could not be read must not come back as a claim
with no reports — those look identical on a screen and mean entirely different things, and a
representative has no way to tell them apart. That is the choice merchant memory makes, and the
opposite of the one the store of past claims makes: there, an answer of "we could not look" is
still an answer a claim can carry on without, and here it is not.

The whole record is kept as text in one column with only the fields a query needs beside it, which
is the shape the store of past claims uses and for the same reason: nothing searches inside a
report.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from claim_agent.report.models import ClaimView, Report
from claim_agent.storage.database import connect, initialise

_UPSERT = """
INSERT INTO reports
    (report_id, version, case_id, claim_line_id, stage, state, created_at, record)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (report_id, version) DO UPDATE SET
    case_id = excluded.case_id,
    claim_line_id = excluded.claim_line_id,
    stage = excluded.stage,
    state = excluded.state,
    created_at = excluded.created_at,
    record = excluded.record
"""

_SELECT_ONE_VERSION = "SELECT record FROM reports WHERE report_id = ? AND version = ?"

# Highest version first, so the first row is the one in force. There is no tie to break: a
# version numbers a report and two rows cannot share one.
_SELECT_LATEST = "SELECT record FROM reports WHERE report_id = ? ORDER BY version DESC LIMIT 1"

_SELECT_VERSIONS = "SELECT record FROM reports WHERE report_id = ? ORDER BY version"

# One row per report — the highest version of each — and never every version of every one. A
# claim's reports are asked for by claim, so without the grouping a claim reworked twice would
# come back with the same product in it three times.
#
# Ordered by when it was written and then by its name, so two reads of one claim always agree.
# Without the second part, two reports written in the same moment could come back either way
# round and a screen would draw the same claim differently twice (NFR-1).
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
    """Reads and writes the reports representatives decide from.

    Everything lives in the one database file the rest of the service uses, created the first time
    this class is used. Each call opens the file, does its one piece of work, and closes it again —
    the same shape as the stores beside it, and for the same reason: these reads take microseconds
    and a shared connection invites a class of bug that is hard to reproduce.

    Nothing in this class judges a claim, writes a report, or decides anything about one. It keeps
    them and hands them back.
    """

    def __init__(self, database_path: Path) -> None:
        """Point the store at a database file.

        Nothing is read or written here, and the file does not have to exist yet: building the
        store is cheap, and the first call that needs the file creates it.

        Args:
            database_path: Where the database file lives, from the settings.
        """
        self._database_path = database_path

    def record(self, report: Report) -> None:
        """Write one version of one report down.

        Writing the same version twice replaces it rather than adding a second copy. That is what
        makes investigating a claim again safe — the second run writes over the first report
        instead of leaving two that disagree — and it is how a report's review state moves on,
        by writing the row again with a new copy of the report (FR-C.4).

        Args:
            report: The report, and which version of it this is.

        Raises:
            StorageError: The database could not be reached or written.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            connection.execute(
                _UPSERT,
                (
                    report.report_id,
                    report.version,
                    report.case_id,
                    report.claim_line_id,
                    report.stage.value,
                    report.state.value,
                    report.created_at.isoformat(timespec="microseconds"),
                    report.model_dump_json(),
                ),
            )

    def get(self, report_id: str, *, version: int | None = None) -> Report | None:
        """Read one report, by default the version in force.

        Args:
            report_id: Which report.
            version: Which telling of it. `None` — the usual case — asks for the highest version
                there is, which is the one a representative is deciding on. Naming one is how an
                earlier version is read back, which is what keeps the record of how a decision was
                reached (FR-R.13).

        Returns:
            The report, or `None` if there is no such report or no such version of it. `None` is
            an answer about this store and never about whether the database could be read — that
            fails instead.

        Raises:
            StorageError: The database could not be reached or read.
        """
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
        """Every version of one report, oldest first (FR-R.13, NFR-5).

        This is the record of how a decision was reached: what was first put in front of a
        representative, what they sent back, and what came back to them.

        Returns:
            The versions, oldest first. Empty for a report that does not exist.

        Raises:
            StorageError: The database could not be reached or read.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_VERSIONS, (report_id,)).fetchall()
        return [Report.model_validate_json(row["record"]) for row in rows]

    def for_case(self, case_id: str) -> ClaimView:
        """Every report on one claim, each at the version in force (FR-2.9b).

        A representative works from a case rather than from a list of disconnected products, so
        this is what a claim looks like: one row per damaged product, or a single row for a claim
        the quick checks stopped before it ever had products in it.

        Returns:
            The claim's reports. An empty list means nobody has asked about this claim yet, which
            is an ordinary answer — a claim whose reports could not be read raises instead, so the
            two can never be mistaken for one another.

        Raises:
            StorageError: The database could not be reached or read.
        """
        initialise(self._database_path)
        with connect(self._database_path) as connection:
            rows = connection.execute(_SELECT_FOR_CASE, (case_id,)).fetchall()
        return ClaimView(
            case_id=case_id,
            reports=tuple(Report.model_validate_json(row["record"]) for row in rows),
        )
