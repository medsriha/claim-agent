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
from claim_agent.api.deps import (
    DecisionStoreDep,
    EvidenceClientDep,
    ImageFetcherDep,
    MerchantMemoryDep,
    ModelsDep,
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
    """What a representative sends when they accept a report (FR-2.8, action 1).

    Every field is optional, because approving a report exactly as it stands is the ordinary case
    and should need nothing said about it.

    `amount_usd` is **text, never a number**. Written as digits with at most two decimal places
    and no currency symbol, such as `"31.20"`. A JSON number would be read as a floating point
    value, where `0.10` cannot be held exactly and cents drift (FR-1.21).

    A figure over the cap is accepted. The cap limits what the *system* may recommend, and no
    requirement says a person may not exceed it — so the decision is recorded as it was made and
    the report says plainly that it went over (FR-1.20, FR-R.8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation | None = None
    amount_usd: str | None = None
    email: EmailWording | None = None
    rep_words: str | None = None
    rep_minutes: int = 0


class SendBack(BaseModel):
    """What a representative sends when a report is not usable as it arrived (FR-2.8, action 2).

    `feedback` is kept exactly as written. It is the whole input to the reworking, and to what is
    remembered against the merchant afterwards, and paraphrasing it here would change both
    (FR-R.3, FR-C.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feedback: str
    rep_minutes: int = 0


@router.get("/cases/{case_id}/reports", summary="The report on one claim")
async def read_claim(case_id: str, reports: ReportStoreDep) -> ClaimView:
    """Find a claim's report, so a representative works from a case (FR-2.9b).

    A claim has at most one report, covering every damaged product on it, so this answers with
    none or one.

    Args:
        case_id: The claim, such as `CASE-1001`.
        reports: Where reports are kept.

    Returns:
        The claim's report at the version in force. **An empty list means nobody has asked for
        this claim to be investigated**, which is an ordinary answer — a claim whose report could
        not be read fails instead, so the two can never be mistaken for one another.
    """
    return reports.for_case(case_id)


@router.get("/reports/{report_id}", summary="Read one report")
async def read_report(
    report_id: str, reports: ReportStoreDep, version: int | None = None
) -> Report:
    """Read one claim's report (FR-2.9a, FR-R.13).

    Args:
        report_id: Which report.
        reports: Where reports are kept.
        version: Which telling of it. Left out — the usual case — reads the one in force. Naming
            one reads back what a representative was looking at earlier, which is the record of
            how a decision was reached (FR-R.13).

    Returns:
        The report, naming every damaged product on the claim.

    Raises:
        NotFoundError: There is no such report, or no such version of it.
    """
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
    """Accept a report, as it stands or after changing it (FR-2.8, FR-2.9, FR-C.1).

    This is the only way a report leaves the review. Nothing else reaches an approval: no time
    limit, no level of confidence, and no number of rounds.

    **Approving sends nothing and pays nothing.** It records that a person accepted a
    recommendation, and nothing in this system acts on one.

    **An approval that changed something is also remembered against the merchant** (FR-C.2,
    FR-3.8), so the next claim they file starts knowing it. An approval that agreed with the
    advice is not: a note saying the system was right would bury the notes saying it was wrong.

    Args:
        report_id: Which report.
        approval: What the representative settled on, and anything they said.
        reports: Where reports are kept.
        decisions: Where what a representative decided is recorded (FR-C.1).
        memory: Where a correction is kept against the merchant (FR-3.8).
        policy: Read for the most the system may recommend on one claim (FR-0.7).

    Returns:
        The approved report, carrying what was advised, what was settled on, and a section saying
        what the representative did.

    Raises:
        NotFoundError: There is no such report.
        InvalidRequestError: A figure was sent that is not an amount written as text.
        ConflictError: The report is already approved and this differs from what was approved.
    """
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
) -> StreamingResponse:
    """Send a report back with a note, and get it reworked around that note (FR-2.8, FR-R.1).

    Three things happen, in this order, and the order matters. What the representative said is
    recorded as a decision, so it survives whatever follows (FR-C.1). It is remembered against
    the merchant, so their next claim starts knowing about it — and so a claim investigated
    again reads it as context (FR-R.14, FR-0.5). Then the agent is given the message and answers.
    Changed decision material is filed as the next version; an answer alone stays on the current
    version (FR-R.9, FR-R.13).

    **Every message is answered.** There is no report this route refuses to pass a message on
    about. What the agent may change differs by report — a claim the quick checks stopped keeps
    its verdict whatever anybody says (FR-R.8) — but the representative always gets a reply.

    **A message can cause a fresh investigation**, when it settles what an unsettled claim is
    for or asks for one outright. That writes a report per damaged product beside this one; the
    reply says so, and the claim's reports are where they appear (FR-1a.4, FR-2.9b).

    Answering takes a model call or several, so progress and the eventual reply are streamed as
    server-sent events rather than making the representative wait in silence.

    **Nothing here sends anything or moves any money**, in either direction. The agent holds
    the investigation's read-only tools and no others (FR-R.6, FR-3.1).

    Args:
        report_id: Which report.
        sending_back: What is wrong or missing, in the representative's own words.
        reports: Where reports and any changed version are kept.
        decisions: Where what a representative decided is recorded (FR-C.1).
        shipbob: Reads the case, parcel and order when the message changes report findings.
        evidence: Reads images and prices the shipment only for a full findings rework.
        fetcher: Downloads an image only when a full findings rework needs to inspect it.
        models: Builds the inexpensive stored-report router and, only when needed, the full
            evidence-rework agent.
        memory: What a representative has corrected for this merchant, which this adds to.
        precedent_store: The closed claims this service has handled, so a reconsidered figure
            is judged the way comparable claims actually were (FR-R.7, FR-S.6).
        policy: The thresholds the rework is judged by (FR-0.7).

    Returns:
        A stream of progress messages, one compact `result` carrying the conversation turn and
        the version of an updated report when one was needed, then `done`. A question whose
        answer changes no report carries no report version and leaves the current version in
        place; the conversation is still recorded on it.

    Raises:
        NotFoundError: There is no such report.
        ConflictError: The report has already been approved, and an approval is final.
    """
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
        events=events,
    )
    revision = answered.revisions[-1]
    report_changed = _report_changed(parked, answered)
    if report_changed:
        stored = answered
        report_version: int | None = answered.version
    else:
        # The exchange belongs to the report, but an answer to a question is not a new telling
        # of its findings. Replace the current row with its appended conversation and leave its
        # identity, timestamp and version untouched.
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
    """Keep what a representative corrected, so the merchant's next claim knows it (FR-R.14, FR-C.2).

    A correction is not only about the claim in hand. A representative who corrects the same thing
    on every claim from one merchant is doing work the system should have done, and this is how
    it stops having to be done twice (FR-3.8).

    **Both review actions arrive here, and they differ in where the sentence comes from.** Sending
    a report back is a correction by definition, and the representative's own words are the
    correction — a summary of them is exactly the thing FR-C.2 warns against, and paraphrasing is
    how a note becomes "the amount was wrong". An approval is a correction only where it *differed*
    from the advice, and there the representative may have typed nothing, so the sentence is built
    from the difference itself and carries the figures.

    `summary` is `None` when an approval agreed with the advice, and nothing is written.

    **Written before the agent is asked, and that order is deliberate.** A claim being
    investigated again reads these corrections as starting context (FR-0.5), so a representative
    settling which products were damaged has their answer reach that investigation through the
    channel that already exists rather than through one invented for it.

    Nothing is stored for a claim that names no merchant, because there is nothing to file it
    against; merchants are identified by the account number, which is stable, and never by the
    brand name, which is display text.

    A store that cannot be written is logged and otherwise ignored. Losing a note against a
    merchant is worth less than losing the answer the representative is waiting for.
    """
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
    """Fetch one report, or say plainly that there is no such thing.

    Raises:
        NotFoundError: There is no such report, or no such version of it. Never raised because
            the store could not be read — that fails with its own answer, so "no such report" and
            "we could not look" are never confused.
    """
    report = reports.get(report_id, version=version)
    if report is None:
        raise NotFoundError(f"There is no report {report_id!r}.")
    return report


def _write_down(
    outcome: ReviewOutcome, *, reports: ReportStore, decisions: DecisionStore
) -> Report:
    """Record what a representative did, then move the report on.

    **The decision is written first, and that order matters.** If the report fails to be written
    afterwards, the retry starts from a report still awaiting review, works out the very same
    decision — the name of a decision comes from what it was about and which decision on that
    report it is, so it does not change — writes over it, and moves the report on. Nothing is
    counted twice and nothing is lost (FR-C.4, FR-3.5).

    The other order cannot heal itself: a report already moved on has nothing left to re-decide,
    so a decision lost on the way would stay lost.

    `outcome.decision` is `None` when nothing happened — the same approval arriving twice — and
    there is then nothing to write.
    """
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
    """Read an amount given as text, or `None` when none was given.

    Args:
        value: An amount written out, such as `"31.20"`. `None` when the representative is not
            changing the figure, which is the ordinary case.

    Raises:
        InvalidRequestError: The text is not an amount. Answered as a 400 rather than being
            quietly treated as "no change", which would approve a figure nobody chose.
    """
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as failure:
        raise InvalidRequestError(
            "amount_usd has to be an amount written as text, such as '31.20'.",
            details={"amount_usd": value},
        ) from failure
