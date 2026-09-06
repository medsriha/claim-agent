from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from claim_agent.analysis.models import AnalysisView
from claim_agent.analysis.performance import summarise
from claim_agent.analysis.view import DEFAULT_PERIOD, build, window_for
from claim_agent.api.deps import DecisionStoreDep
from claim_agent.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/performance", summary="How the system has been doing over a stretch of time")
async def read_performance(
    store: DecisionStoreDep,
    period: str = Query(
        default=DEFAULT_PERIOD,
        description="Which stretch of time to cover. An unknown one falls back to the default.",
    ),
) -> AnalysisView:
    """Answer with every figure the analysis screen draws."""
    now = datetime.now(UTC)
    starts_at, ends_at = window_for(period, now)
    decisions = store.decided_between(starts_at, ends_at)
    logger.info(
        "analysis_read",
        period=period,
        starts_at=starts_at.isoformat(),
        ends_at=ends_at.isoformat(),
        decisions=len(decisions),
    )
    return build(summarise(decisions, starts_at, ends_at), period, now)
