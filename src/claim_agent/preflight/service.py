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
    """Screen one claim and say whether it can be processed at all (FR-0.3)."""
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
        case_id=record.case.case_id,
        verdict=verdict,
        terminal_reasons=reasons,
        gates=gates,
        record=record,
        context=context,
        report=report,
        evaluated_at=evaluated_at,
    )
