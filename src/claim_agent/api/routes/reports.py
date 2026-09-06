from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.events import EventStream, RunEvent
from claim_agent.agent.threads import PassThreads
from claim_agent.api.deps import (
    DecisionStoreDep,
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
from claim_agent.domain.correction import correction_from
from claim_agent.domain.models import MerchantCorrection
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ClaimAgentError, InvalidRequestError, NotFoundError, StorageError
from claim_agent.observability import get_logger
from claim_agent.report.conversation import answer_the_representative
from claim_agent.report.models import ClaimView, EmailWording, Report
from claim_agent.report.review import ReviewOutcome, approve, send_back
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)

router = APIRouter(tags=["reports"])

STREAM_MEDIA_TYPE = "text/event-stream"
_QUEUE_LIMIT = 256


class Approval(BaseModel):
    """What a representative sends when they accept a report (FR-2.8, action 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation | None = None
    amount_usd: str | None = None
    email: EmailWording | None = None
    rep_words: str | None = None
    rep_minutes: int = 0


class SendBack(BaseModel):
    """What a representative sends when a report is not usable as it arrived (FR-2.8, action 2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feedback: str
    rep_minutes: int = 0


@router.get("/cases/{case_id}/reports", summary="The report on one claim")
async def read_claim(case_id: str, reports: ReportStoreDep) -> ClaimView:
    """Find a claim's report, so a representative works from a case (FR-2.9b)."""
    return reports.for_case(case_id)


@router.get("/reports/{report_id}", summary="Read one report")
async def read_report(
    report_id: str, reports: ReportStoreDep, version: int | None = None
) -> Report:
    """Read one claim's report (FR-2.9a, FR-R.13)."""
    return _the_report(reports, report_id, version=version)


@router.post("/reports/{report_id}/approve", summary="Approve a report")
async def approve_report(
    report_id: str,
    approval: Approval,
    reports: ReportStoreDep,
    decisions: DecisionStoreDep,
    memory: MerchantMemoryDep,
    policy: PolicyDep,
) -> Report:
    """Accept a report, as it stands or after changing it (FR-2.8, FR-2.9, FR-C.1)."""
    report = _the_report(reports, report_id)
    outcome = approve(
        report,
        decided_outcome=approval.outcome,
        decided_amount_usd=_amount(approval.amount_usd),
        edited_email=approval.email,
        rep_words=approval.rep_words,
        rep_minutes=approval.rep_minutes,
        policy=policy,
        at=datetime.now(UTC),
    )
    approved = _write_down(outcome, reports=reports, decisions=decisions)
    if outcome.decision is not None:
        _remember_against_the_merchant(memory, approved, summary=correction_from(outcome.decision))
    return approved


@router.post(
    "/reports/{report_id}/send-back",
    summary="Send a report back with feedback",
    response_class=StreamingResponse,
)
async def send_report_back(
    report_id: str,
    sending_back: SendBack,
    reports: ReportStoreDep,
    decisions: DecisionStoreDep,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    memory: MerchantMemoryDep,
    precedent_store: PrecedentStoreDep,
    policy: PolicyDep,
    threads: PassThreadsDep,
) -> StreamingResponse:
    """Send a report back with a note, and get it reworked around that note (FR-2.8, FR-R.1)."""
    asked_at = datetime.now(UTC)
    report = _the_report(reports, report_id)
    outcome = send_back(
        report,
        feedback=sending_back.feedback,
        rep_minutes=sending_back.rep_minutes,
        at=asked_at,
    )
    parked = _write_down(outcome, reports=reports, decisions=decisions)
    _remember_against_the_merchant(memory, parked, summary=sending_back.feedback)

    return StreamingResponse(
        _narrate_rework(
            parked=parked,
            feedback=sending_back.feedback,
            at=asked_at,
            reports=reports,
            shipbob=shipbob,
            evidence=evidence,
            fetcher=fetcher,
            models=models,
            memory=memory,
            precedent_store=precedent_store,
            policy=policy,
            threads=threads,
        ),
        media_type=STREAM_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _narrate_rework(
    *,
    parked: Report,
    feedback: str,
    at: datetime,
    reports: ReportStore,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: PolicyDep,
    threads: PassThreads,
) -> AsyncIterator[str]:
    """Stream a representative's answer and only point at a report when it changed."""
    messages: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=_QUEUE_LIMIT)
    events = EventStream(messages.put)
    answering = asyncio.create_task(
        _answer_and_record(
            parked=parked,
            feedback=feedback,
            at=at,
            reports=reports,
            shipbob=shipbob,
            evidence=evidence,
            fetcher=fetcher,
            models=models,
            memory=memory,
            precedent_store=precedent_store,
            policy=policy,
            threads=threads,
            events=events,
        )
    )

    async for message in _rework_messages_until_finished(answering, messages):
        yield message

    try:
        result = answering.result()
    except ClaimAgentError as failure:
        logger.warning(
            "representative_answer_failed",
            report_id=parked.report_id,
            failure=type(failure).__name__,
        )
        yield _frame("failed", {"code": failure.code, "message": failure.message})
        yield _frame("done", {"report_id": parked.report_id})
        return

    yield _frame("result", result)
    yield _frame("done", {"report_id": parked.report_id})


async def _answer_and_record(
    *,
    parked: Report,
    feedback: str,
    at: datetime,
    reports: ReportStore,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: PolicyDep,
    threads: PassThreads,
    events: EventStream,
) -> dict[str, Any]:
    """Record the reply, creating a report version only when report content changed."""
    answered = await answer_the_representative(
        parked,
        feedback=feedback,
        at=at,
        shipbob=shipbob,
        evidence=evidence,
        fetcher=fetcher,
        models=models,
        memory=memory,
        precedent_store=precedent_store,
        policy=policy,
        threads=threads,
        events=events,
    )
    revision = answered.revisions[-1]
    report_changed = _report_changed(parked, answered)
    if report_changed:
        stored = answered
        report_version: int | None = answered.version
    else:
        stored = answered.model_copy(
            update={"version": parked.version, "created_at": parked.created_at}
        )
        report_version = None
    reports.record(stored)

    logger.info(
        "representative_was_answered",
        case_id=stored.case_id,
        report_id=stored.report_id,
        version=stored.version,
        report_changed=report_changed,
    )
    return {
        "report_id": stored.report_id,
        "report_version": report_version,
        "revision": revision.model_dump(mode="json"),
    }


def _report_changed(before: Report, after: Report) -> bool:
    """Whether the agent changed decision material rather than only answering a question."""
    return any(
        getattr(before, field) != getattr(after, field)
        for field in (
            "product_names",
            "stage",
            "recommendation",
            "amount_usd",
            "confidence",
            "carrier",
            "defect_type",
            "damage_type",
            "order_value_usd",
            "drafted_email",
            "content",
        )
    )


async def _rework_messages_until_finished(
    answering: asyncio.Task[dict[str, Any]], messages: asyncio.Queue[RunEvent]
) -> AsyncIterator[str]:
    """Forward progress in order, including events queued as the task finishes."""
    while True:
        next_message = asyncio.ensure_future(messages.get())
        finished, _ = await asyncio.wait(
            {next_message, answering}, return_when=asyncio.FIRST_COMPLETED
        )
        if next_message in finished:
            yield _frame("progress", next_message.result().model_dump(mode="json"))
            continue

        next_message.cancel()
        while not messages.empty():
            yield _frame("progress", messages.get_nowait().model_dump(mode="json"))
        return


def _frame(name: str, payload: dict[str, Any]) -> str:
    """Write one named SSE message whose data is compact JSON on one line."""
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _remember_against_the_merchant(
    memory: MerchantMemory, report: Report, *, summary: str | None
) -> None:
    """Keep what a representative corrected, so the merchant's next claim knows it (FR-R.14, FR-C.2)."""
    if summary is None or report.user_id is None:
        return
    try:
        memory.record_correction(
            MerchantCorrection(
                user_id=report.user_id,
                case_id=report.case_id,
                summary=summary,
                recorded_at=datetime.now(UTC),
            )
        )
    except StorageError:
        logger.warning(
            "correction_not_remembered", case_id=report.case_id, report_id=report.report_id
        )


def _the_report(reports: ReportStore, report_id: str, *, version: int | None = None) -> Report:
    """Fetch one report, or say plainly that there is no such thing."""
    report = reports.get(report_id, version=version)
    if report is None:
        raise NotFoundError(f"There is no report {report_id!r}.")
    return report


def _write_down(
    outcome: ReviewOutcome, *, reports: ReportStore, decisions: DecisionStore
) -> Report:
    """Record what a representative did, then move the report on."""
    if outcome.decision is not None:
        decisions.record(outcome.decision)
        logger.info(
            "representative_decided",
            case_id=outcome.report.case_id,
            report_id=outcome.report.report_id,
            action=outcome.decision.action.value,
        )
    reports.record(outcome.report)
    return outcome.report


def _amount(value: str | None) -> Decimal | None:
    """Read an amount given as text, or `None` when none was given."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as failure:
        raise InvalidRequestError(
            "amount_usd has to be an amount written as text, such as '31.20'.",
            details={"amount_usd": value},
        ) from failure
