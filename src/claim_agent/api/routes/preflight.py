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
    """Run the four eligibility checks on one claim and answer with what they found.

    The case id is the whole input; there is nothing to send in the body.

    This is asked for as a POST even though it changes nothing today. Screening is a
    step in the claim pipeline, and once results are kept the step will record one.
    Callers wired to a read-only request today would all break on the day that
    happens, and moving them later is more expensive than being honest now. The
    trade-off is that a step which is genuinely side-effect-free today does not look
    it.

    Args:
        case_id: The claim's case id, such as `CASE-1001`.
        shipbob: The reader for the case, its parcel and its order (FR-0.1).
        merchant_memory: What a rep has already corrected for this merchant (FR-0.5).
        policy: The thresholds the checks judge against (FR-0.7).

    Returns:
        Everything the screen read, what each of the four checks found, the facts
        worked out up front, and the verdict. A stopped claim also carries the
        report a rep reads and approves; a claim allowed through carries none, and
        no reasons.

    Raises:
        NotFoundError: ShipBob has no case with this id. Answered as a 404.
        UpstreamError: ShipBob could not be reached, failed, or replied with
            something unreadable. Answered as a 502, because a claim we could not
            read must never be mistaken for a claim with nothing in it (NFR-4).
    """
    # The one and only time this layer looks at a clock, and it is deliberately here
    # at the edge rather than inside the screening itself. Everything below is handed
    # the moment instead of asking for it, which is what lets the same claim be
    # screened twice and answer identically, and what lets a test pin the time
    # (FR-0.6).
    return await run_preflight(
        case_id=case_id,
        client=shipbob,
        memory=merchant_memory,
        policy=policy,
        evaluated_at=datetime.now(UTC),
    )
