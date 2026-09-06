from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from claim_agent.agent.events import EventKind, EventStream, RunEvent
from claim_agent.agent.run import ClaimInvestigation, investigate_claim
from claim_agent.api.deps import (
    EvidenceClientDep,
    ImageFetcherDep,
    MerchantMemoryDep,
    ModelsDep,
    PassThreadsDep,
    PolicyDep,
    PrecedentStoreDep,
    ReportStoreDep,
    ShipBobClientDep,
)
from claim_agent.domain.models import Verdict
from claim_agent.errors import ClaimAgentError, StorageError
from claim_agent.observability import get_logger
from claim_agent.preflight.models import PreflightResult
from claim_agent.preflight.service import run_preflight
from claim_agent.report.build import build_investigation_report, build_screening_report
from claim_agent.report.models import Report
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)

router = APIRouter(tags=["investigation"])

STREAM_MEDIA_TYPE = "text/event-stream"
"""How a browser is told this reply arrives in pieces rather than all at once."""

_QUEUE_LIMIT = 256
"""How many unsent messages may pile up before the investigation is made to wait."""


@router.post(
    "/cases/{case_id}/investigate",
    summary="Investigate a claim, narrated as it happens",
    response_class=StreamingResponse,
)
async def investigate_case(
    case_id: str,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    merchant_memory: MerchantMemoryDep,
    precedent_store: PrecedentStoreDep,
    reports: ReportStoreDep,
    policy: PolicyDep,
    threads: PassThreadsDep,
) -> StreamingResponse:
    """Screen a claim, investigate it, and say so as it goes."""

    asked_at = datetime.now(UTC)

    return StreamingResponse(
        _narrate(
            case_id=case_id,
            asked_at=asked_at,
            shipbob=shipbob,
            evidence=evidence,
            fetcher=fetcher,
            models=models,
            merchant_memory=merchant_memory,
            precedent_store=precedent_store,
            reports=reports,
            policy=policy,
            threads=threads,
        ),
        media_type=STREAM_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _narrate(
    *,
    case_id: str,
    asked_at: datetime,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    merchant_memory: MerchantMemoryDep,
    precedent_store: PrecedentStoreDep,
    reports: ReportStoreDep,
    policy: PolicyDep,
    threads: PassThreadsDep,
) -> AsyncIterator[str]:
    """Do the work and yield each message as it happens."""
    messages: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=_QUEUE_LIMIT)
    events = EventStream(messages.put)

    try:
        screening = await run_preflight(
            case_id=case_id,
            client=shipbob,
            memory=merchant_memory,
            policy=policy,
            evaluated_at=asked_at,
        )
    except ClaimAgentError as failure:
        logger.warning(
            "investigation_could_not_start", case_id=case_id, failure=type(failure).__name__
        )
        yield _frame("failed", {"code": failure.code, "message": failure.message})
        yield _frame("done", {"case_id": case_id})
        return

    yield _frame(
        "progress",
        _screening_message(screening).model_dump(mode="json"),
    )

    if screening.verdict is Verdict.TERMINAL:
        ready, could_not_keep = _keep(reports, build_screening_report(screening, at=asked_at))
        yield _frame("progress", (await _say_it_is_ready(events, ready, could_not_keep)))
        yield _frame("result", _report_message(ready, could_not_keep))
        yield _frame("done", {"case_id": screening.case_id})
        return

    try:
        chat, structured = models()
    except ClaimAgentError as failure:
        logger.warning(
            "investigation_needs_a_model_it_cannot_have",
            case_id=screening.case_id,
            failure=type(failure).__name__,
        )
        yield _frame("failed", {"code": failure.code, "message": failure.message})
        yield _frame("done", {"case_id": screening.case_id})
        return

    investigating = asyncio.create_task(
        investigate_claim(
            record=screening.record,
            context=screening.context,
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            events=events,
            policy=policy,
            precedent_store=precedent_store,
            threads=threads,
        )
    )

    async for frame in _messages_until_it_finishes(investigating, messages):
        yield frame

    try:
        investigated = investigating.result()
    except ClaimAgentError as failure:
        logger.warning(
            "investigation_failed", case_id=screening.case_id, failure=type(failure).__name__
        )
        yield _frame("failed", {"code": failure.code, "message": failure.message})
        yield _frame("done", {"case_id": screening.case_id})
        return

    ready, could_not_keep = _keep(
        reports, build_investigation_report(screening, investigated, at=asked_at)
    )
    yield _frame("progress", (await _say_it_is_ready(events, ready, could_not_keep)))
    yield _frame("result", _report_message(ready, could_not_keep))
    yield _frame("done", {"case_id": screening.case_id})


async def _messages_until_it_finishes(
    investigating: asyncio.Task[ClaimInvestigation],
    messages: asyncio.Queue[RunEvent],
) -> AsyncIterator[str]:
    """Write out what the investigation says, until it has nothing left to say."""
    while True:
        next_message = asyncio.ensure_future(messages.get())
        finished, _ = await asyncio.wait(
            {next_message, investigating}, return_when=asyncio.FIRST_COMPLETED
        )

        if next_message in finished:
            yield _frame("progress", next_message.result().model_dump(mode="json"))
            continue

        next_message.cancel()
        while not messages.empty():
            yield _frame("progress", messages.get_nowait().model_dump(mode="json"))
        return


def _screening_message(screening: PreflightResult) -> RunEvent:
    """Turn the deterministic screen's verdict into the stream's first message."""
    stopped = screening.verdict is Verdict.TERMINAL
    reasons = ", ".join(reason.value.replace("_", " ") for reason in screening.terminal_reasons)
    return RunEvent(
        sequence=0,
        kind=EventKind.SCREENED,
        summary=(
            f"This claim cannot be processed: {reasons}."
            if stopped
            else "The claim passed the eligibility checks, so the investigation begins."
        ),
        detail={
            "verdict": screening.verdict.value,
            "checks_passed": str(sum(1 for gate in screening.gates if gate.passed)),
            "checks_run": str(len(screening.gates)),
        },
    )


def _keep(reports: ReportStore, built: Report | None) -> tuple[Report | None, str | None]:
    """Write the finished report down, and never fail the claim for not managing it."""
    if built is None:
        return None, None

    try:
        reports.record(built)
    except StorageError as failure:
        logger.error(
            "report_not_kept",
            case_id=built.case_id,
            report_id=built.report_id,
            failure=type(failure).__name__,
        )
        return (
            built,
            "These findings could not be kept, so they cannot be approved yet. "
            "Asking for this claim again will try to keep them.",
        )
    return built, None


def _report_message(report: Report | None, could_not_keep: str | None) -> dict[str, Any]:
    """The part of the result that says what a representative can now decide on."""
    return {
        "report": None if report is None else report.model_dump(mode="json"),
        "report_unavailable_reason": could_not_keep,
    }


async def _say_it_is_ready(
    events: EventStream, kept: Report | None, could_not_keep: str | None
) -> dict[str, Any]:
    """Announce the finished report as the last thing the investigation says."""
    if could_not_keep is not None:
        summary = could_not_keep
    elif kept is None:
        summary = "There is nothing to review on this claim."
    else:
        summary = "The report is ready for review."

    event = await events.emit(
        EventKind.REPORT_READY,
        summary,
        outcome="kept" if could_not_keep is None else "not_kept",
    )
    return event.model_dump(mode="json")


def _frame(name: str, payload: dict[str, Any]) -> str:
    """Write one server-sent event."""
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
