from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from claim_agent.domain.models import MerchantCorrection
from claim_agent.settings import get_settings
from claim_agent.storage.merchant_memory import MerchantMemory

DEMO_MERCHANT_USER_ID = "334430"


DEMO_CORRECTION = MerchantCorrection(
    user_id=DEMO_MERCHANT_USER_ID,
    case_id="CASE-0912",
    summary=("Rep reduced the payout to the single damaged ampoule; the second item was unopened."),
    recorded_at=datetime(2026, 1, 14, 9, 30, tzinfo=UTC),
)


def seed(database_path: Path) -> str:
    """Add the demo correction, unless the merchant already has it."""
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
    """Remove every correction from the store."""
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
