from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from claim_agent.observability import get_logger

logger = get_logger(__name__)


class EventKind(StrEnum):
    """The kinds of thing an investigation says about itself as it goes."""

    SCREENED = "screened"
    ATTACHMENTS_LISTED = "attachments_listed"
    IMAGE_CLASSIFIED = "image_classified"
    EVIDENCE_SETTLED = "evidence_settled"
    CLAIM_SPLIT = "claim_split"
    PRECEDENT_GATHERED = "precedent_gathered"
    INVESTIGATION_STARTED = "investigation_started"
    TOOL_CALLED = "tool_called"
    THINKING = "thinking"
    INVESTIGATION_FINISHED = "investigation_finished"
    REVISION_STARTED = "revision_started"
    REPORT_READY = "report_ready"
    FAILED = "failed"


class RunEvent(BaseModel):
    """One thing worth telling a representative while the investigation runs."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sequence: int
    kind: EventKind
    summary: str
    detail: Mapping[str, str] = Field(default_factory=dict)


EventSink = Callable[[RunEvent], Awaitable[None]]


class EventStream:
    """Hands out sequence numbers and passes events on to whoever is listening."""

    def __init__(self, sink: EventSink | None = None) -> None:
        """Start a stream, optionally forwarding to somebody watching."""
        self._sink = sink
        self._events: list[RunEvent] = []
        self._lock = asyncio.Lock()

    async def emit(
        self,
        kind: EventKind,
        summary: str,
        **detail: str,
    ) -> RunEvent:
        """Say that something happened, and pass it to whoever is watching."""
        async with self._lock:
            event = RunEvent(
                sequence=len(self._events) + 1,
                kind=kind,
                summary=summary,
                detail=dict(detail),
            )
            self._events.append(event)

        if self._sink is not None:
            try:
                await self._sink(event)
            except Exception as exc:
                logger.warning(
                    "event_not_delivered",
                    event_kind=kind.value,
                    failure=type(exc).__name__,
                )
        return event

    def events(self) -> tuple[RunEvent, ...]:
        """Everything said so far, in the order it was said."""
        return tuple(self._events)
