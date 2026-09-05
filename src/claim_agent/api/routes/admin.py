"""Reading and changing the claim policy over HTTP (FR-0.7, NFR-7).

Almost every threshold this system judges a claim by is a placeholder we invented
so the code would run — only the $100 reimbursement cap is a real ShipBob figure.
They all live in one file so they can be corrected without touching any logic, but
until this existed, correcting one meant setting an environment variable and
restarting the service. Three of these addresses let someone read the values, change
them, and put them back, and a change takes effect on the very next claim screened.

**A fourth empties the merchant corrections**, so a demonstration can start from a system that
remembers nothing. It is here rather than anywhere else because it is an operator's act on the
running service, like a threshold change — and like one, it is undone by nobody, since the
whole point of the store is that the system does not forget.

**There is no sign-in.** Anyone who can reach these addresses can change what every
claim after them is judged by, and nothing records who did it. That is the same
choice the rest of this demonstration makes, and it is written up in DESIGN.md
under "Future production" rather than being quietly hoped over.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from claim_agent.admin.models import ForgottenCorrections, PolicyUpdate, PolicyView
from claim_agent.admin.panel import describe_policy, revise_policy
from claim_agent.api.deps import LivePolicyDep, MerchantMemoryDep
from claim_agent.observability import get_logger

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


@router.post("/corrections/forget", summary="Forget every correction held against a merchant")
async def forget_corrections(memory: MerchantMemoryDep) -> ForgottenCorrections:
    """Empty the store of what representatives have corrected, for every merchant (FR-3.8).

    **This is a demonstration control, and it destroys real history.** Every claim after it is
    screened and investigated as though no representative had ever corrected anything for that
    merchant — which is the point when somebody wants to show the system learning from
    nothing, and a genuine loss otherwise. There is no undo, no record of who did it, and no
    sign-in in front of it.

    It removes everything or nothing. Choosing which of a representative's corrections to
    forget is a judgement nobody has specified, and offering it would invite quietly deleting
    an inconvenient one.

    Args:
        memory: The store of what representatives have corrected (FR-0.5).

    Returns:
        How many corrections were removed. Zero is an ordinary answer: there were none.

    Raises:
        StorageError: The database could not be reached or written.
    """
    forgotten = memory.forget_everything()
    logger.info("merchant_corrections_forgotten", forgotten=forgotten)
    return ForgottenCorrections(forgotten=forgotten)
