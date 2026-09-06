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
    """Where one pass keeps its conversation, so a later pass can pick it up (FR-R.2)."""

    checkpointer: BaseCheckpointSaver[Any]
    thread_id: str


class PassThreads:
    """The conversations of every investigation this process has run."""

    def __init__(self) -> None:
        """Start with no conversations remembered."""
        self._saver = MemorySaver()

    def start(self, case_id: str) -> PassThread:
        """Open a fresh thread for a new investigation of this claim."""
        thread = PassThread(checkpointer=self._saver, thread_id=f"{case_id}:{uuid4().hex[:8]}")
        logger.info("pass_thread_started", case_id=case_id, thread_id=thread.thread_id)
        return thread

    def resume(self, thread_id: str) -> PassThread:
        """Hand back the thread with this name, for a pass that continues it."""
        return PassThread(checkpointer=self._saver, thread_id=thread_id)

    async def remembers(self, thread_id: str | None) -> bool:
        """Say whether a conversation with this name is still held here."""
        if thread_id is None:
            return False
        held = await self._saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        return held is not None
