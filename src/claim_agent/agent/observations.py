from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from claim_agent.observability import get_logger

logger = get_logger(__name__)

# Deliberately unrestricted: the memo never looks inside an answer, and naming the type
# is what lets a caller get back exactly what it asked for.
T = TypeVar("T")


class ObservationCache:
    """A per-claim memo of expensive answers, so each question is answered once (NFR-8)."""

    def __init__(self) -> None:
        """Open an empty memo for one claim."""
        # Answers are held as plain objects because the memo never looks inside one; the
        # caller gets its own type back through `get_or_compute`.
        self._answers: dict[str, object] = {}
        # One lock per question. It is what makes two callers asking the same question at
        # the same moment produce one piece of work rather than two.
        self._locks: dict[str, asyncio.Lock] = {}
        self._computed_count = 0

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[T]]) -> T:
        """Answer a question, doing the work only if this claim has not already done it."""
        # Asked with `in` rather than by fetching and checking for nothing, because
        # `None` is a real answer here and must not read as an absent one.
        if key in self._answers:
            logger.info("observation_reused", observation=key)
            return cast(T, self._answers[key])

        # `setdefault` settles who owns the lock without awaiting anything in between, so
        # two callers arriving together cannot end up with a lock each.
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Asked again inside the lock: while this caller was waiting, the one holding
            # the lock may have been answering this very question.
            if key in self._answers:
                logger.info("observation_reused", observation=key)
                return cast(T, self._answers[key])

            # Counted before the work starts, so an attempt that fails still shows up. A
            # failed answer costs what a successful one costs, and the count is here to
            # make the cost of a claim visible (NFR-8).
            self._computed_count += 1
            answer = await compute()
            self._answers[key] = answer
            return answer

    def keys(self) -> tuple[str, ...]:
        """Name every question this claim has an answer for, oldest first."""
        return tuple(self._answers)

    @property
    def computed_count(self) -> int:
        """How many times the expensive work was actually started for this claim."""
        return self._computed_count
