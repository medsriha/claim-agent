"""Put a rep's past correction into merchant memory, so the demo has one to show.

**Everything this writes is invented.** No part of the running system records a rep's
corrections yet: the store can be read and can be written, the screen reads it, and the
code that would write to it belongs to a later stage that does not exist (FR-3.8). So on
any fresh machine every claim honestly reports "None on file for this merchant", and the
panel that would show a merchant's history is always empty.

That is correct and it demonstrates nothing. This tool exists so someone showing the
system can make that panel show something, **knowing** that what it shows was typed by
hand rather than learned from a rep.

It writes the one correction the repository already documents: `layer0-http-transcript.txt`
records a real response for CASE-1001 carrying exactly this note, because whoever captured
that transcript seeded it the same way. The database is not in version control, so the row
never travelled with the file — which leaves the transcript showing history the screen
cannot. Running this makes the two agree again, and it is the reason this writes that
correction rather than one of its own devising.

**It is a development tool.** It writes through the same store the service reads, so what
appears on screen went in the way a real correction would. Nothing in `src/` can reach it,
and production never runs it.

    uv run python -m tools.seed_merchant_memory           # add it, if it is not there
    uv run python -m tools.seed_merchant_memory --clear   # take it back out

`--clear` matters as much as the writing does: fabricated history on screen is
indistinguishable from the real thing, so there has to be an obvious way to undo it.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from claim_agent.domain.models import MerchantCorrection
from claim_agent.settings import get_settings
from claim_agent.storage.merchant_memory import MerchantMemory

# Best Paw Nutrition, the merchant on CASE-1001 — the one sample claim whose case, parcel
# and order are all quoted in full in REQUIREMENTS.md. Keyed on the account number, never
# the brand name, because the name is display text a merchant can edit (FR-3.8).
DEMO_MERCHANT_USER_ID = "334430"

# Word for word the correction in `layer0-http-transcript.txt`. Note the case id does not
# follow this project's convention of starting invented identifiers with a 9 — it is
# reproduced as the transcript has it rather than corrected, so the two match exactly.
DEMO_CORRECTION = MerchantCorrection(
    user_id=DEMO_MERCHANT_USER_ID,
    case_id="CASE-0912",
    summary=("Rep reduced the payout to the single damaged ampoule; the second item was unopened."),
    recorded_at=datetime(2026, 1, 14, 9, 30, tzinfo=UTC),
)


def seed(database_path: Path) -> str:
    """Add the demo correction, unless the merchant already has it.

    Checked before writing because the store has no notion of a duplicate — a rep really
    might correct the same thing twice, so the store is right not to refuse it, and this
    tool is the thing that has to be safe to run twice.

    Args:
        database_path: The database file the service reads, from the settings.

    Returns:
        A sentence saying what happened, for whoever ran it.
    """
    memory = MerchantMemory(database_path)
    already = memory.corrections_for(DEMO_MERCHANT_USER_ID)
    if any(one.case_id == DEMO_CORRECTION.case_id for one in already):
        return f"Already there: {DEMO_MERCHANT_USER_ID} has the correction from CASE-0912."

    memory.record_correction(DEMO_CORRECTION)
    return (
        f"Seeded one invented correction against merchant {DEMO_MERCHANT_USER_ID}. "
        "CASE-1001 will now show it under past rep corrections."
    )


def clear(database_path: Path) -> str:
    """Remove every correction from the store.

    Reaches past the store's own methods and deletes rows directly, because the store
    deliberately has no way to delete one: the system never forgets a rep's correction, and
    giving it that ability so a demo could tidy up after itself would be the wrong trade.
    Undoing something a development tool invented is a job for a development tool.

    Args:
        database_path: The database file the service reads, from the settings.

    Returns:
        A sentence saying how many corrections were removed.
    """
    if not database_path.exists():
        return f"Nothing to clear: {database_path} does not exist yet."

    with sqlite3.connect(database_path) as connection:
        removed = connection.execute("DELETE FROM rep_corrections").rowcount
    return f"Cleared {removed} correction(s). Every claim reports none on file again."


def main() -> int:
    """Read what was asked for, do it, and say what happened."""
    parser = argparse.ArgumentParser(
        description="Seed or clear the invented rep correction the demo shows.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove every correction instead of adding one",
    )
    arguments = parser.parse_args()

    database_path = get_settings().database_path
    print(clear(database_path) if arguments.clear else seed(database_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
