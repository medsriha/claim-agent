"""Put a few past rep corrections into the store, so the demo has some to show.

When a rep changes something the system recommended, that correction is kept against the
merchant and the next claim from them starts out knowing about it (FR-0.5, FR-3.8). The
screening reads those corrections and passes them on.

Nothing writes them yet: the code that captures a rep's edits belongs to a later stage
that has not been built. So on a fresh machine the store is empty, every claim shows "no
corrections on file", and there is no way to see that half of the screening working at
all. This puts a few in.

**Invented, every one of them.** Nobody at ShipBob wrote these corrections and no rep made
them. They follow the repository's convention for made-up identifiers: every case id here
starts with a 9, so it can never be mistaken for one ShipBob supplied. The merchant
account numbers are real, and are the ones the sample claims are filed under, which is
what makes the corrections show up when those claims are screened.

Run it with `make seed`. Running it twice adds the corrections twice, which is untidy but
harmless — the store keeps whatever it is given, and deleting the database file resets it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from claim_agent.domain.models import MerchantCorrection
from claim_agent.settings import get_settings
from claim_agent.storage.merchant_memory import MerchantMemory

# Two merchants with history, so the demo shows both a claim that carries corrections and
# one that carries none. The rest of the sample merchants are deliberately left clean.
DEMO_CORRECTIONS = [
    MerchantCorrection(
        user_id="334430",
        case_id="CASE-9912",
        summary=(
            "Rep reduced the payout to the single damaged ampoule; the second item in the "
            "box was unopened and undamaged."
        ),
        recorded_at=datetime(2026, 1, 14, 9, 30, tzinfo=UTC),
    ),
    MerchantCorrection(
        user_id="334430",
        case_id="CASE-9948",
        summary=(
            "Rep asked for a photograph of the outer box before paying; the merchant's "
            "first set of photographs only showed the product."
        ),
        recorded_at=datetime(2026, 2, 2, 16, 5, tzinfo=UTC),
    ),
    MerchantCorrection(
        user_id="373103",
        case_id="CASE-9931",
        summary=(
            "Rep matched the claim to the 90-count tub rather than the 30-count; the two "
            "look identical in a photograph and the prices differ."
        ),
        recorded_at=datetime(2026, 1, 28, 11, 15, tzinfo=UTC),
    ),
]


def seed() -> None:
    """Write the demo corrections into whichever database the settings point at.

    Raises:
        StorageError: The store could not be written — the path is unusable, the disk is
            full, the file is not a database.
    """
    memory = MerchantMemory(get_settings().database_path)
    for correction in DEMO_CORRECTIONS:
        memory.record_correction(correction)


if __name__ == "__main__":
    seed()
