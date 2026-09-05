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
    """Answer with every figure the analysis screen draws.

    The period is named rather than given as two dates, so the screen never works out a date
    boundary of its own and two people asking for "12 months" on the same day always get the same
    window. An unrecognised name falls back to the default instead of failing: a way of looking at
    the past is not the kind of thing where being wrong is dangerous, and an error page teaches a
    reader nothing.

    Args:
        store: The record of what representatives decided.
        period: One of the keys the reply itself lists under `presets`.

    Returns:
        The tiles, the charts, the candidate rules and the assumptions behind the money. Every
        number arrives twice — once as a value to draw and once as the words to read — so nothing
        in the browser has to work anything out (FR-1.21, NFR-2).

    Raises:
        StorageError: The record of decisions could not be read. This fails the whole request
            rather than coming back as an empty period, because the two mean opposite things.
    """
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
