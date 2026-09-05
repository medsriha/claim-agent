"""Working out the handful of facts the investigation should not have to work out itself.

A claim arrives as three records — the case a merchant opened, the parcel, and
the order behind it — plus whatever a rep has corrected for that merchant before.
Four things follow from those records by arithmetic alone: what the order was
worth, whether that counts as a high-value order, how long the merchant waited
before filing, and which delivery date those days were counted from.

Doing that here means the investigation is handed the answers instead of
rediscovering them, which saves it steps and, more importantly, makes the answers
the same every time (FR-0.5, FR-0.6). It also means the number a rep reads in a
report is the same number the eligibility checks used, rather than a second
calculation that might disagree with the first (NFR-3).

Nothing here reads a file, calls an API, or looks at a clock. Everything it needs
is passed in, so the same inputs always produce the same facts.
"""

from __future__ import annotations

from collections.abc import Sequence

from claim_agent.domain.dates import whole_days_between
from claim_agent.domain.high_value import is_high_value
from claim_agent.domain.models import MerchantCorrection
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext, DeliveryDate


def build_context(
    record: CaseRecord,
    delivery: DeliveryDate,
    corrections: Sequence[MerchantCorrection],
    policy: Policy,
) -> ClaimContext:
    """Work out the starting facts for one claim (FR-0.5).

    Args:
        record: The case, and the parcel and order it points at. Either of the
            last two may be missing, because the case named none or because the
            record could not be read.
        delivery: The delivery date the checks settled on, and where it came
            from. It carries no date at all when neither record had one.
        corrections: What a rep has previously corrected for this merchant, in
            the order they were made. Usually empty.
        policy: Where the high-value figure lives, so the number that decides it
            can be changed without touching this code (FR-0.7, NFR-7).

    Returns:
        The facts, ready to hand to the investigation or to write into a report
        for a rep. `order_value_usd` is `None` when the order could not be read,
        which is not the same as an order worth nothing, and
        `days_since_delivery` is `None` when no delivery date is known.
    """
    order_value_usd = record.order.total_value if record.order is not None else None
    return ClaimContext(
        order_value_usd=order_value_usd,
        is_high_value=is_high_value(order_value_usd, policy),
        days_since_delivery=_days_waited_before_filing(delivery, record),
        delivered_date=delivery.value,
        merchant_corrections=tuple(corrections),
    )


def _days_waited_before_filing(delivery: DeliveryDate, record: CaseRecord) -> int | None:
    """Count the days between the parcel arriving and the merchant opening the case.

    Read the name of the field this fills — `days_since_delivery` — as "days from
    delivery to the claim being filed", not "days from delivery until today". The
    count deliberately ends at the moment the case was created, for two reasons.
    It is the same count the age check used, so a report cannot say one number
    while the decision rested on another (NFR-3). And it never changes: a claim
    that was 73 days old the day it was filed is still 73 days old when someone
    reopens the report next year, so a stored report never quietly goes stale and
    the layer stays deterministic (FR-0.6).

    Args:
        delivery: The delivery date the checks settled on.
        record: The case, which carries the moment the merchant filed.

    Returns:
        Whole calendar days, or `None` when no delivery date is known and there
        is therefore nothing to measure from. The number can be negative if the
        records say a case was opened before its own parcel arrived, which real
        data does occasionally claim; it is passed on as it is rather than
        tidied away.
    """
    if delivery.value is None:
        return None
    return whole_days_between(delivery.value, record.case.created_date)
