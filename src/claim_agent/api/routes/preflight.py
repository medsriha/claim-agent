from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from claim_agent.api.deps import MerchantMemoryDep, PolicyDep, ShipBobClientDep
from claim_agent.preflight.models import PreflightResult
from claim_agent.preflight.service import run_preflight

router = APIRouter(tags=["preflight"])


@router.post("/cases/{case_id}/preflight", summary="Screen a claim for eligibility")
async def screen_case(
    case_id: str,
    shipbob: ShipBobClientDep,
    merchant_memory: MerchantMemoryDep,
    policy: PolicyDep,
) -> PreflightResult:
    """Run the four eligibility checks on one claim and answer with what they found."""

    return await run_preflight(
        case_id=case_id,
        client=shipbob,
        memory=merchant_memory,
        policy=policy,
        evaluated_at=datetime.now(UTC),
    )
