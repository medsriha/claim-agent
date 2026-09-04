"""The single file on disk where this service keeps what it has to remember.

Some things cannot be looked up in ShipBob because ShipBob has nowhere to put
them. Today that is one thing: the corrections a support rep made on a merchant's
earlier claims, which the next claim from that merchant should start out knowing
about (FR-0.5, FR-3.8).

Those go into one SQLite database file. SQLite is a database that lives entirely
in a single file, with no server to run alongside the service. It was chosen
because it survives a restart, needs nothing installed, and can be opened and
read by hand when someone wants to see what is actually stored.

This module owns two things only: what tables exist, and how the file is opened
and closed safely. What goes in the tables is decided next door. The file and its
tables are created the first time anything uses them, so there is no setup step
for anyone to forget.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from claim_agent.errors import UpstreamError
from claim_agent.observability import get_logger

logger = get_logger(__name__)

# The tables, written so that running this on an existing database changes
# nothing. `id` counts up on its own with each row, which also makes it the
# tie-breaker when two corrections carry the same moment: the one written first
# has the lower number, so a read can always put them back in the order they
# arrived (FR-0.6). `recorded_at` is text rather than a number because a date
# anyone can read in the file is worth more here than a few saved bytes; it is
# always written in UTC, so sorting the text sorts the moments.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS rep_corrections (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS rep_corrections_by_user ON rep_corrections (user_id);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the database file for one piece of work, then close it again.

    Use it with `with`: the block gets an open connection, anything written
    inside the block is saved when the block ends normally, and undone if the
    block raises. The connection is closed either way. The folder holding the
    file is created if it is not there, and so is the file itself, which is what
    makes first use need no setting up.

    A fresh connection each time is deliberate. A connection to a SQLite file
    belongs to the thread that opened it, and sharing one across a web service
    invites a class of bug that is hard to reproduce. These reads take
    microseconds, so there is nothing to gain by holding one open.

    Args:
        path: The database file. It does not have to exist yet.

    Yields:
        An open connection whose rows can be read by column name.

    Raises:
        UpstreamError: The database could not be opened, read or written — the
            file is not a database, the disk is full, the path is unusable. The
            failure is translated here so that no caller has to know this service
            stores anything in SQLite, and so that a broken store fails loudly
            instead of looking like a merchant with no history (NFR-4, NFR-6).

    Failures raised inside the `with` block are translated too, and that is the
    important half: opening a file that is not a database quietly succeeds, and
    it is the first query against it that finds out.
    """
    connection: sqlite3.Connection | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        with connection:
            yield connection
    except (sqlite3.Error, OSError) as failure:
        # The path is logged rather than returned. It says something about the
        # machine this runs on, and error responses leave the building.
        logger.error("claim_database_unavailable", database_path=str(path), error=str(failure))
        raise UpstreamError(
            "The store of past claim corrections could not be reached."
        ) from failure
    finally:
        if connection is not None:
            connection.close()


def initialise(path: Path) -> None:
    """Make sure the database file exists and has the tables this service needs.

    Safe to call as often as you like: every statement it runs asks for something
    to be created only if it is not there already, so the second call changes
    nothing and the hundredth is no different. Callers therefore do not have to
    track whether the database has been set up — they can simply ask for it
    before each piece of work.

    Args:
        path: The database file. It is created, along with its folder, if absent.

    Raises:
        UpstreamError: The database could not be created or opened.
    """
    with connect(path) as connection:
        connection.executescript(_SCHEMA)
