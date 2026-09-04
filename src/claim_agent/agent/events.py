"""What the investigation says about itself while it is still working.

An investigation takes a while. It reads a case, looks at photographs one at a
time, works out which products were damaged, and only then reaches a
recommendation. A representative watching a blank screen for half a minute has no
idea whether anything is happening, which of several products is being worked on,
or whether it has quietly failed.

So the run narrates itself. Each time something happens worth seeing, it emits one
of these, and the web layer forwards them to the screen as they arrive. The
finished report and its drafted email follow at the end, on the same stream.

**These are the service's own words, not the screen's.** The screen adds labels
and nothing else — it never works out a verdict, re-orders anything, or writes a
sentence of its own about what the system found. That rule is what keeps the
browser a window onto the investigation rather than a second opinion about it, and
it is why `summary` is written here rather than assembled there.

**This is not the audit trail.** The run also keeps a ledger of what it did, which
travels inside the finished report and is the record of how a decision was reached
(NFR-3, NFR-5). The two look similar and are not: a ledger belongs to one product's
run and lives as long as the report, while this stream covers the whole claim —
the screening, the split, every product — and lives only as long as somebody is
watching. Neither can be recovered from the other.

**Nothing here decides anything.** A run that emits no events at all reaches
exactly the same recommendation. If the stream fails, the investigation carries on
and the reply still arrives (NFR-4).

Nothing here reads a clock. Order comes from a sequence number this module hands
out, so two runs of the same claim narrate themselves identically (NFR-1).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from claim_agent.observability import get_logger

logger = get_logger(__name__)


class EventKind(StrEnum):
    """The kinds of thing an investigation says about itself as it goes.

    They fall into three groups. `SCREENED`, `ATTACHMENTS_LISTED`,
    `IMAGE_CLASSIFIED`, `EVIDENCE_SETTLED` and `CLAIM_SPLIT` are about the claim
    as a whole, and happen once. `LINE_STARTED`, `TOOL_CALLED`, `THINKING` and
    `LINE_FINISHED` are about one damaged product, and happen once per product —
    several products are investigated at the same time, so these interleave, and
    every one of them names the product it belongs to.

    `REPORT_READY` carries a finished report and its drafted email. `FAILED` is
    the last thing a stream ever says when something went wrong, and it exists so
    that a screen never simply stops with no explanation (NFR-4).

    `TOOL_CALLED` is the interesting one to watch: it is the investigation
    choosing what to look at next, which is the whole reason this is an agent and
    not a fixed sequence of steps (FR-1.1).
    """

    SCREENED = "screened"
    ATTACHMENTS_LISTED = "attachments_listed"
    IMAGE_CLASSIFIED = "image_classified"
    EVIDENCE_SETTLED = "evidence_settled"
    CLAIM_SPLIT = "claim_split"
    LINE_STARTED = "line_started"
    TOOL_CALLED = "tool_called"
    THINKING = "thinking"
    LINE_FINISHED = "line_finished"
    REPORT_READY = "report_ready"
    FAILED = "failed"


class RunEvent(BaseModel):
    """One thing worth telling a representative while the investigation runs.

    `summary` is a plain sentence written by the service, ready to put on screen
    with no rewording — "Looked at ATT-CASE-1001-02: a photograph of a broken
    bottle". `detail` carries the same facts in named parts, for a screen that
    wants to lay them out rather than print the sentence.

    `claim_line_id` names the damaged product this is about, and is `None` for
    the events that concern the whole claim. Several products are investigated at
    once, so without it a screen could not tell which of them a message belongs
    to.

    Everything in `detail` is text. Nothing here carries a monetary amount: money
    reaches a screen only in a finished report, where it was worked out by
    arithmetic rather than written by a model (FR-1.21).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    sequence: int
    kind: EventKind
    summary: str
    claim_line_id: str | None = None
    detail: Mapping[str, str] = Field(default_factory=dict)


EventSink = Callable[[RunEvent], Awaitable[None]]
"""Where an event goes once it has been made.

The web layer supplies one that puts the event on a queue for the browser. A test
supplies one that appends to a list. Passing `None` where a sink is expected
turns narration off, which is what every test of the rules themselves does.
"""


class EventStream:
    """Hands out sequence numbers and passes events on to whoever is listening.

    One of these per claim, shared by the claim-level pass and by every product's
    run, which is what lets a screen show several products being worked on at once
    and still put every message in a fixed order.

    Safe to use from several runs at the same time: the sequence number is handed
    out under a lock, so two products finishing at the same instant cannot be
    given the same position.
    """

    def __init__(self, sink: EventSink | None = None) -> None:
        """Start a stream, optionally forwarding to somebody watching.

        Args:
            sink: Where to send each event. `None` keeps them and sends them
                nowhere, which is what a test or a caller that only wants the
                finished report does.
        """
        self._sink = sink
        self._events: list[RunEvent] = []
        self._lock = asyncio.Lock()

    async def emit(
        self,
        kind: EventKind,
        summary: str,
        *,
        claim_line_id: str | None = None,
        **detail: str,
    ) -> RunEvent:
        """Say that something happened, and pass it to whoever is watching.

        A sink that fails is logged and otherwise ignored, deliberately. Somebody
        closing their browser mid-investigation must not fail the claim: the run
        carries on and the report is still produced, because narrating the work is
        not part of doing it (NFR-4).

        Args:
            kind: Which sort of thing happened.
            summary: One plain sentence, ready to put on screen unchanged.
            claim_line_id: The damaged product this concerns, if it concerns one.
            **detail: The same facts in named parts, all of them text.

        Returns:
            The event, already numbered and already sent.
        """
        async with self._lock:
            event = RunEvent(
                sequence=len(self._events) + 1,
                kind=kind,
                summary=summary,
                claim_line_id=claim_line_id,
                detail=dict(detail),
            )
            self._events.append(event)

        if self._sink is not None:
            try:
                await self._sink(event)
            except Exception as exc:
                # Every failure is caught here on purpose, and this is the one
                # place in the system where that is right. Whoever is watching is
                # outside our control: a browser closes, a connection drops, a
                # queue fills. None of that says anything about the claim, and
                # none of it may be allowed to stop an investigation that is
                # otherwise going fine. The alternative — letting a dropped
                # connection fail a claim — is the failure mode NFR-4 exists to
                # prevent.
                logger.warning(
                    "event_not_delivered",
                    event_kind=kind.value,
                    failure=type(exc).__name__,
                )
        return event

    def events(self) -> tuple[RunEvent, ...]:
        """Everything said so far, in the order it was said."""
        return tuple(self._events)
