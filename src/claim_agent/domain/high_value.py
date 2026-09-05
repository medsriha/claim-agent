"""The one comparison that decides whether a figure counts as high value (FR-0.5, FR-C.7)."""

from __future__ import annotations

from decimal import Decimal

from claim_agent.policy import Policy


def is_high_value(value_usd: Decimal | None, policy: Policy) -> bool:
    """Say whether a figure in dollars is dear enough that a representative should be told.

    Two questions ask it: whether the order behind a claim is a high-value one, and whether
    the damaged goods themselves are. They share a threshold, so they share this function —
    two comparisons against one number could otherwise be given two different meanings.

    Args:
        value_usd: The figure, or `None` when it could not be worked out.
        policy: Holds the figure to reach and whether landing exactly on it counts. Both
            are judgement calls nobody has confirmed, which is why they are settings.

    Returns:
        False when the figure is unknown. That means "not known to be high value", never
        "known to be ordinary": a value nobody could read must not raise a flag, and must
        not put one to rest either.
    """
    if value_usd is None:
        return False
    if policy.high_value_inclusive:
        return value_usd >= policy.high_value_order_usd
    return value_usd > policy.high_value_order_usd
