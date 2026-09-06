from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from claim_agent.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PassThread:
    """Where one pass keeps its conversation, so a later pass can pick it up (FR-R.2).

    A thread is the graph's own record of every message a pass exchanged: the claim it
    was shown, every tool it called and what came back, and everything it said. Handing
    the same thread to a later pass makes that pass a continuation of the conversation
    rather than a retelling of it.
    """

    checkpointer: BaseCheckpointSaver[Any]
    thread_id: str


class PassThreads:
    """The conversations of every investigation this process has run.

    This is what the graph framework is for. A representative who sends a report back
    is answered by the investigation that wrote it — the pass that already looked at
    the photographs, priced the shipment and weighed the evidence — continuing from
    where it stopped, with the note appended. Without this, a rework has to rebuild
    that context from a prose summary of the report, re-read images it has already
    read, and answer from a description of its own work rather than the work itself.

    Kept in memory for the life of the process, deliberately. A thread that has gone —
    after a restart — is not a failure: the report remembers which thread it came from,
    `remembers` says the thread is no longer here, and the rework falls back to
    rebuilding its context from the report. Durable storage is one line to add when a
    deployment wants threads to outlive the process; the fallback stays either way.
    """

    def __init__(self) -> None:
        """Start with no conversations remembered."""
        self._saver = MemorySaver()

    def start(self, case_id: str) -> PassThread:
        """Open a fresh thread for a new investigation of this claim.

        Fresh every time on purpose. Investigating a claim again is a new conversation,
        and appending it to the old one would put two investigations' worth of evidence
        in front of a model that was asked for one.
        """
        thread = PassThread(checkpointer=self._saver, thread_id=f"{case_id}:{uuid4().hex[:8]}")
        logger.info("pass_thread_started", case_id=case_id, thread_id=thread.thread_id)
        return thread

    def resume(self, thread_id: str) -> PassThread:
        """Hand back the thread with this name, for a pass that continues it."""
        return PassThread(checkpointer=self._saver, thread_id=thread_id)

    async def remembers(self, thread_id: str | None) -> bool:
        """Say whether a conversation with this name is still held here.

        `None` — a report that recorded no thread — is answered with no, so a caller can
        ask about whatever the report carries without checking first.
        """
        if thread_id is None:
            return False
        held = await self._saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        return held is not None
