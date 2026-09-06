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
    """Answer with every claim threshold, what it holds, and what it started as."""
    return describe_policy(live)


@router.put("/policy", summary="Change the claim policy")
async def change_policy(update: PolicyUpdate, live: LivePolicyDep) -> PolicyView:
    """Put new thresholds in force, for every claim screened from now on."""
    current = live.current()
    revised = revise_policy(current, update)
    changed = [name for name in update.values if getattr(revised, name) != getattr(current, name)]

    live.replace(revised, changed_at=datetime.now(UTC))

    logger.info("claim_policy_changed", changed_values=changed)
    return describe_policy(live)


@router.post("/policy/reset", summary="Put back the claim policy the service started with")
async def reset_policy(live: LivePolicyDep) -> PolicyView:
    """Undo every change, back to the values the service was started with."""
    live.reset()
    logger.info("claim_policy_reset")
    return describe_policy(live)


@router.post("/forget-everything", summary="Empty every store the service keeps")
async def forget_everything(settings: SettingsDep) -> ClearedStores:
    """Throw away everything the service has remembered, so a demonstration starts from nothing."""
    cleared = empty_every_store(settings.database_path)
    logger.info(
        "every_store_emptied",
        corrections=cleared.corrections,
        reports=cleared.reports,
        decisions=cleared.decisions,
        past_claims=cleared.past_claims,
    )
    return cleared
