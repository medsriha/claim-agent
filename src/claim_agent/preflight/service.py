"""Running the pre-flight screen from end to end (FR-0.3).

This is the one place that puts the cheap screen together: read the claim, settle on a
delivery date, run the four eligibility checks, work out the facts the investigation
should not have to work out for itself, and answer either "carry on" or "stop, and here
is the explanation the merchant is owed".

Nothing is decided here. Every rule lives in a file of its own and is a plain rule over
data that has already been read, so this file is a running order and not a judgement.
There is no AI anywhere in this layer, and no clock is consulted, which together are why
screening the same claim twice gives the same answer both times (FR-0.6).
"""

from __future__ import annotations

from datetime import datetime

from claim_agent.domain.models import Verdict
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.context import build_context
from claim_agent.preflight.gates import evaluate_gates, resolve_delivered_date, terminal_reasons
from claim_agent.preflight.gather import gather_case_record
from claim_agent.preflight.models import PreflightResult
from claim_agent.preflight.report import build_terminal_report
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.storage.merchant_memory import MerchantMemory

logger = get_logger(__name__)


async def run_preflight(
    *,
    case_id: str,
    client: ShipBobClient,
    memory: MerchantMemory,
    policy: Policy,
    evaluated_at: datetime,
) -> PreflightResult:
    """Screen one claim and say whether it can be processed at all (FR-0.3).

    Reads the claim, checks it against the four eligibility rules, and gathers the
    starting facts. A claim that clears all four is passed on for investigation. A
    claim that fails any of them stops here and comes back with a write-up for a
    support representative, which includes a drafted email to the merchant that
    nothing sends on its own (FR-0.4, FR-0.5).

    Args:
        case_id: The support case to screen, for example `CASE-1001`.
        client: The reader for the ShipBob API.
        memory: What representatives have corrected on this merchant's earlier claims.
        policy: The thresholds every check judges against, kept in one named place so
            they can be changed without touching this code (FR-0.7).
        evaluated_at: When this screen was asked for. The caller supplies it; this
            layer never reads a clock. No rule uses it — it is a stamp for the record,
            saying when the answer was produced. Keeping the single impure moment out
            at the edge of the system is what makes the promise of determinism
            something a test can check: the same claim screened today, tomorrow, or in
            ten years gives an identical result apart from this stamp (FR-0.6).

    Returns:
        The verdict, all four check results whichever way it went, everything that was
        read, the starting facts, and — only on a stopped claim — the write-up for the
        representative.

    Raises:
        NotFoundError: ShipBob has no case with this id.
        UpstreamError: ShipBob could not be reached or could not be understood, or the
            store of past corrections could not be read. Every one of those stops the
            screen with an error a person sees, rather than a verdict resting on
            information we do not actually have (NFR-4).
    """
    record = await gather_case_record(case_id, client)
    delivery = resolve_delivered_date(record)
    gates = evaluate_gates(record, delivery, policy)
    reasons = terminal_reasons(gates)
    corrections = memory.corrections_for(record.case.user_id)
    context = build_context(record, delivery, corrections, policy)

    verdict = Verdict.TERMINAL if reasons else Verdict.PROCEED
    report = (
        build_terminal_report(record.case, reasons, gates, context, policy) if reasons else None
    )

    logger.info(
        "preflight_completed",
        case_id=record.case.case_id,
        verdict=verdict.value,
        terminal_reasons=[reason.value for reason in reasons],
    )
    return PreflightResult(
        # The id comes from the record we actually read rather than the one we asked
        # for, so the result and the write-up inside it can never name different cases.
        case_id=record.case.case_id,
        verdict=verdict,
        terminal_reasons=reasons,
        gates=gates,
        record=record,
        context=context,
        report=report,
        evaluated_at=evaluated_at,
    )
