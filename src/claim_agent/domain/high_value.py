from __future__ import annotations

from decimal import Decimal

from claim_agent.policy import Policy


def is_high_value(value_usd: Decimal | None, policy: Policy) -> bool:
    """Say whether a figure in dollars is dear enough that a representative should be told."""
    if value_usd is None:
        return False
    if policy.high_value_inclusive:
        return value_usd >= policy.high_value_order_usd
    return value_usd > policy.high_value_order_usd
