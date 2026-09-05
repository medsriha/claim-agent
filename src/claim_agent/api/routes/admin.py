from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from claim_agent.admin.models import PolicyUpdate, PolicyView
from claim_agent.admin.panel import describe_policy, revise_policy
from claim_agent.api.deps import LivePolicyDep, SettingsDep
from claim_agent.observability import get_logger
from claim_agent.storage.reset import ClearedStores, empty_every_store

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/policy", summary="Read the claim policy in force")
async def read_policy(live: LivePolicyDep) -> PolicyView:
    """Answer with every claim threshold, what it holds, and what it started as.

    Args:
        live: The policy in force (FR-0.7).

    Returns:
        One entry per value, in the order the policy file declares them, each with
        the sentence from that file explaining what it is for. Several of those
        sentences say the value is provisional and awaiting ShipBob's sign-off,
        which is worth showing rather than hiding.
    """
    return describe_policy(live)


@router.put("/policy", summary="Change the claim policy")
async def change_policy(update: PolicyUpdate, live: LivePolicyDep) -> PolicyView:
    """Put new thresholds in force, for every claim screened from now on.

    Anything left out of the request keeps the value it already has, so one value
    can be changed without restating the rest.

    A change is all or nothing. If any submitted value is refused, the policy is
    left exactly as it was and the reply says which values were refused and why —
    a policy made of some accepted values and some rejected ones is not something
    a claim should ever be judged by (NFR-4).

    Args:
        update: The values to change, by name. Numbers and amounts of money arrive
            as text so that no amount ever passes through a browser number
            (FR-1.21, NFR-2).
        live: The policy in force, which this replaces.

    Returns:
        The policy now in force, in the same shape reading it gives, so a caller
        never has to guess what its change actually did.

    Raises:
        InvalidRequestError: A name that is no part of the policy, or a value the
            policy will not accept. Answered as a 400, with a complaint per value.
    """
    current = live.current()
    revised = revise_policy(current, update)
    changed = [name for name in update.values if getattr(revised, name) != getattr(current, name)]
    # The clock is read here, at the edge, and the moment handed inwards — the same
    # way screening does it, so that nothing deeper down depends on the time.
    live.replace(revised, changed_at=datetime.now(UTC))
    # Worth a line in the log even in a demonstration: it is the only trace that a
    # claim screened after this point was judged by different numbers than one
    # screened before it. Names only; the values are in the reply.
    logger.info("claim_policy_changed", changed_values=changed)
    return describe_policy(live)


@router.post("/policy/reset", summary="Put back the claim policy the service started with")
async def reset_policy(live: LivePolicyDep) -> PolicyView:
    """Undo every change, back to the values the service was started with.

    Those are whatever the environment said at startup, or the built-in defaults.
    Nothing is stored anywhere, so this is also what a restart would do.

    Args:
        live: The policy in force.

    Returns:
        The policy now in force, which is the one the service started with.
    """
    live.reset()
    logger.info("claim_policy_reset")
    return describe_policy(live)


@router.post("/forget-everything", summary="Empty every store the service keeps")
async def forget_everything(settings: SettingsDep) -> ClearedStores:
    """Throw away everything the service has remembered, so a demonstration starts from nothing.

    **This is a demonstration control, and it destroys real history.** Four stores go: what
    representatives have corrected for each merchant (FR-3.8), every report and every earlier
    version of one (FR-R.13), the record of what representatives decided (FR-C.1), and the past
    closed claims a new claim is priced against (FR-S.1). There is no undo, no record of who did
    it, and no sign-in in front of it.

    **Emptying the corrections alone is not starting fresh**, which is why this takes the rest
    too. A claim already investigated keeps its report, so opening it again shows the whole
    back-and-forth with the representative still there, and the report still lists the
    corrections it was written from — it holds a copy rather than looking them up again.

    It removes everything or nothing. Choosing which of a representative's corrections to
    forget is a judgement nobody has specified, and offering it would invite quietly deleting
    an inconvenient one.

    Args:
        settings: Read for where the database file lives.

    Returns:
        How many records went from each store. All zeroes is an ordinary answer: there was
        nothing there.

    Raises:
        StorageError: The database could not be reached or written. Nothing was removed.
    """
    cleared = empty_every_store(settings.database_path)
    logger.info(
        "every_store_emptied",
        corrections=cleared.corrections,
        reports=cleared.reports,
        decisions=cleared.decisions,
        past_claims=cleared.past_claims,
    )
    return cleared
