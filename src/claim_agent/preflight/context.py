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
    """Compute the deterministic starting facts for a claim."""
    order_value_usd = record.order.total_value if record.order is not None else None
    return ClaimContext(
        order_value_usd=order_value_usd,
        is_high_value=is_high_value(order_value_usd, policy),
        days_since_delivery=_days_waited_before_filing(delivery, record),
        delivered_date=delivery.value,
        merchant_corrections=tuple(corrections),
    )


def _days_waited_before_filing(delivery: DeliveryDate, record: CaseRecord) -> int | None:
    """Count whole days from delivery to filing, if delivery is known."""
    if delivery.value is None:
        return None
    return whole_days_between(delivery.value, record.case.created_date)
