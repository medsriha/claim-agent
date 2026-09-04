"""Investigating a claim over HTTP, narrated as it happens.

An investigation takes a while. It screens the claim, reads photographs one at a
time, looks up how comparable claims were decided, works out which products were
damaged, and only then reaches a recommendation for each of them. Answering that
in one reply at the end means a representative watches a blank screen for most of
a minute with no idea whether anything is happening, which of several products is
being worked on, or whether it has quietly failed.

So this streams. Each thing the investigation does is sent as it happens, and the
finished reports and their drafted emails follow at the end, on the same
connection. The screen shows the work rather than a plausible imitation of it —
which matters, because the screen used to invent the pacing itself, and DESIGN.md
recorded that as the largest gap between what it showed and what the system did.

**A stopped claim never reaches the agent.** Screening runs first, and a claim it
turns away costs three cheap reads and no AI at all (NFR-8). Its explanation comes
back on the same stream, so a caller has one thing to consume either way.

**Nothing here decides anything.** Every recommendation is a proposal, every email
is a draft, and neither this route nor anything it can reach is able to send an
email or move money — those live behind a representative's approval, in a package
the investigation cannot import (FR-1.2, FR-3.1).
"""

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
    PolicyDep,
    PrecedentStoreDep,
    ShipBobClientDep,
)
from claim_agent.domain.models import Verdict
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.preflight.models import PreflightResult
from claim_agent.preflight.service import run_preflight

logger = get_logger(__name__)

router = APIRouter(tags=["investigation"])

STREAM_MEDIA_TYPE = "text/event-stream"
"""How a browser is told this reply arrives in pieces rather than all at once."""

_QUEUE_LIMIT = 256
"""How many unsent messages may pile up before the investigation is made to wait.

Only reached when a reader is slower than the investigation, which in practice means
a reader that has gone away. A bound rather than none, because an unbounded queue
turns a reader that stopped listening into memory this process never gets back.
"""


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
    policy: PolicyDep,
) -> StreamingResponse:
    """Screen a claim, investigate every damaged product on it, and say so as it goes.

    The case id is the whole input; there is nothing to send in the body.

    What comes back is a stream of named messages. `progress` messages say what the
    investigation is doing — which image it looked at, what past claims it found,
    which tool it chose to call next. One `result` message near the end carries
    everything a representative decides from: the split, each product's findings,
    its recommendation, how its amount was worked out, and its drafted email. A
    `done` message closes the stream, and a `failed` message appears instead of one
    if something went wrong (NFR-4).

    A claim the screen turns away sends its explanation as the `result` and never
    reaches the agent, so it costs no AI at all (NFR-8).

    Args:
        case_id: The claim's case id, such as `CASE-1001`.
        shipbob: The reader for the case, its shipment and its order (FR-0.1).
        evidence: The reader for the case's images and a priced invoice.
        fetcher: How an image is downloaded so a model can look at it.
        models: A way to build the models, asked only once the claim is going on.
            A claim the screen turns away never needs one, so it is never built for
            one — an ineligible claim must not fail for want of a credential (NFR-8).
        merchant_memory: What a representative has already corrected for this
            merchant (FR-0.5).
        precedent_store: The closed claims this service has handled before, looked
            up per product so a claim is judged the way comparable ones were
            (FR-S.5).
        policy: The thresholds every judgement is made against (FR-0.7).

    Returns:
        A stream of server-sent events. The status is 200 as soon as the stream
        opens, because that is all a stream can promise — a claim turned away and a
        claim investigated in full are both successful outcomes of asking, and a
        failure part-way through is reported inside the stream rather than by a
        status nobody can still change.
    """
    # The one and only time this route reads a clock, deliberately at the edge:
    # everything below is handed the moment instead of asking for it, which is what
    # lets the same claim be screened twice and answer identically (FR-0.6).
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
            policy=policy,
        ),
        media_type=STREAM_MEDIA_TYPE,
        headers={
            # Streamed replies are ruined by anything that buffers them: a proxy
            # holding messages back to send them together defeats the whole point.
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
    policy: PolicyDep,
) -> AsyncIterator[str]:
    """Do the work and yield each message as it happens.

    The shape of this is worth understanding, because getting it wrong loses
    messages. The investigation runs as its own task and pushes what it says onto a
    queue; this loop takes from that queue and writes it out. When the task
    finishes, the queue is drained before the final result is sent — otherwise the
    last few things the investigation said would be dropped on the floor at exactly
    the moment they matter most.

    Every failure ends the stream with a `failed` message rather than an empty
    connection or a stack trace. A caller must always be left with something they
    can act on (NFR-4).
    """
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
        # A case ShipBob does not have, or a ShipBob that cannot be reached. The
        # stream has already begun, so there is no status left to change: the reason
        # is sent as a message instead.
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
        # Stopped before anything expensive. The explanation a representative has to
        # approve is the whole result, and no image was ever looked at (FR-0.4, NFR-8).
        yield _frame("result", {"screening": screening.model_dump(mode="json")})
        yield _frame("done", {"case_id": screening.case_id})
        return

    try:
        chat, structured = models()
    except ClaimAgentError as failure:
        # Only reached for a claim that was going on, which is the only kind that needs
        # a model. The stream has begun, so this is said rather than returned.
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

    yield _frame("result", _result_message(screening, investigated))
    yield _frame("done", {"case_id": screening.case_id})


async def _messages_until_it_finishes(
    investigating: asyncio.Task[ClaimInvestigation],
    messages: asyncio.Queue[RunEvent],
) -> AsyncIterator[str]:
    """Write out what the investigation says, until it has nothing left to say.

    Waits on the next message and on the investigation finishing at the same time,
    so a long silence does not hold the stream open past the end of the work and a
    message never has to wait for a poll to notice it.

    The drain at the end is the part that matters. An investigation can say several
    things and finish in the same breath, and stopping as soon as the task is done
    would throw those away — including, on a claim that failed, the messages saying
    what it managed to establish first.
    """
    while True:
        next_message = asyncio.ensure_future(messages.get())
        finished, _ = await asyncio.wait(
            {next_message, investigating}, return_when=asyncio.FIRST_COMPLETED
        )

        if next_message in finished:
            yield _frame("progress", next_message.result().model_dump(mode="json"))
            continue

        # The work is done. Whatever it said on the way out is still in the queue.
        next_message.cancel()
        while not messages.empty():
            yield _frame("progress", messages.get_nowait().model_dump(mode="json"))
        return


def _screening_message(screening: PreflightResult) -> RunEvent:
    """Turn the deterministic screen's verdict into the stream's first message.

    Written here rather than inside the screen because the screen predates the
    stream and has no business knowing about it — it answers in one piece, and
    always did.
    """
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


def _result_message(screening: PreflightResult, investigated: ClaimInvestigation) -> dict[str, Any]:
    """Assemble the one message a representative actually decides from.

    Carries the screening as well as the investigation, so that everything behind a
    recommendation is in one place and nothing has to be fetched again to check it
    (NFR-3). Sent whole rather than in pieces because a report read half-arrived is
    worse than one that arrives a moment later.
    """
    return {
        "screening": screening.model_dump(mode="json"),
        "investigation": investigated.model_dump(mode="json"),
    }


def _frame(name: str, payload: dict[str, Any]) -> str:
    """Write one server-sent event.

    The format is fixed by the browser: a named event, its data on one line, and a
    blank line to end it. The data is put on a single line because a newline inside
    it would be read as the end of the message — which is why it is JSON with no
    formatting rather than anything easier to read.
    """
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
