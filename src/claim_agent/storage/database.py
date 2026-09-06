from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from claim_agent.errors import StorageError
from claim_agent.observability import get_logger

logger = get_logger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rep_corrections (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS rep_corrections_by_user ON rep_corrections (user_id);

CREATE TABLE IF NOT EXISTS precedent_lines (
    precedent_id TEXT PRIMARY KEY,
    claim_line_id TEXT NOT NULL,
    withdrawn INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT NOT NULL,
    record TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS precedent_lines_live ON precedent_lines (withdrawn);

CREATE VIRTUAL TABLE IF NOT EXISTS precedent_search USING fts5 (
    precedent_id UNINDEXED,
    words
);

CREATE TABLE IF NOT EXISTS rep_decisions (
    decision_id TEXT PRIMARY KEY,
    decided_at TEXT NOT NULL,
    record TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS rep_decisions_by_time ON rep_decisions (decided_at);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (report_id, version)
);

CREATE INDEX IF NOT EXISTS reports_by_case ON reports (case_id);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the database file for one piece of work, then close it again."""
    connection: sqlite3.Connection | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        with connection:
            yield connection
    except (sqlite3.Error, OSError) as failure:
        logger.error("claim_database_unavailable", database_path=str(path), error=str(failure))
        raise StorageError("The store of past claim corrections could not be reached.") from failure
    finally:
        if connection is not None:
            connection.close()


def initialise(path: Path) -> None:
    """Make sure the database file exists and has the tables this service needs."""
    with connect(path) as connection:
        connection.executescript(_SCHEMA)
