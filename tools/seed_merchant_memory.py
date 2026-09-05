"""Put a rep's past correction into merchant memory, so the demo has one to show.

**Everything this writes is invented.** The running system does now record a rep's
corrections — sending a report back stores their words, and approving after changing the
figure stores the difference (FR-R.14, FR-C.2) — so this tool is no longer the only way to
fill the panel. It stays because a fresh machine still starts with an empty store, and
because a demonstration sometimes needs history to exist before it begins rather than being
made during it.

**Which means what it writes can no longer be told apart from a real correction on screen.**
Both are rows in the same store, put there through the same method, and nothing marks either.
Anyone demonstrating this should say which they are looking at, or run `--clear` first and
make a real one instead — CASE-9005 exists so that they can (FR-C.8).

It writes one fixed correction rather than a different one each run: the merchant, the case
number and the wording were all chosen by hand and never change, so that two people
demonstrating the system see the same history and a screenshot still matches the screen a
month later. The database is not in version control, so nothing carries the row between
machines — a fresh clone shows an empty panel until somebody runs this.

**It is a development tool.** It writes through the same store the service reads, so what
appears on screen went in the way a real correction would. Nothing in `src/` can reach it,
and production never runs it.

    uv run python -m tools.seed_merchant_memory           # add it, if it is not there
    uv run python -m tools.seed_merchant_memory --clear   # take it back out

`--clear` matters as much as the writing does: fabricated history on screen is
indistinguishable from the real thing, so there has to be an obvious way to undo it.

**This file has an expiry date, and it is later than it looks.** TODO.md's FR-C.8 note sets
the condition: not when the real write exists, but when a rep can decide a claim *and* the
demo data holds a second case for a merchant who already has a decided one. Until all three
are true, a real correction would be written and no later claim would ever see it.
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

# Invented, like everything else in this file. Note the case id does not follow this
# project's convention of starting a made-up identifier with a 9, so unlike the constructed
# claims in the ShipBob stand-in it does not announce itself as ours at a glance.
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
