"""Asking over HTTP how the system has been doing.

Every other address in this service answers a question about one claim. This one answers a
question about all of them: over some stretch of time, how often did a representative take the
advice exactly as it stood, how far did they change it when they did, how long did it take, what
was that worth, and — the reason the address exists — did the system's own statement of how sure
it was turn out to predict whether anyone agreed with it.

**No requirement asks for this.** REQUIREMENTS.md does not mention measurement, reporting or
automation, so nothing here carries a requirement id of its own. Two requirements do bear on it
and are named where they apply: FR-C.7, whose open question about expensive claims is the shape
of the rules this scores, and FR-C.8, which governs the invented data that fills it today.

**Nothing here is a control.** FR-2.9 says a report leaves review in exactly one way — a person
approving it — and that no confidence level and no number of revisions changes that. FR-3.1
calls the same thing a hard invariant. So the candidate rules this scores are evidence for a
conversation about changing those requirements, not settings anybody can turn on, and the reply
says so in its own words rather than leaving it to be inferred.

**An empty period and an unreadable store are different answers.** A stretch of time nobody
decided anything in comes back as a success, with a sentence saying so, because that is an
ordinary thing for a quiet month to look like. A store that cannot be read fails the whole
request instead, so a reader sees one honest failure rather than a screen full of panels each
claiming to be empty. Reporting the second as the first would tell somebody the system is not
being used when the truth is that nobody looked.
"""

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
