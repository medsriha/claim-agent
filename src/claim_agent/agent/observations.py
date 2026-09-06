from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from claim_agent.observability import get_logger

logger = get_logger(__name__)


T = TypeVar("T")


class ObservationCache:
    """A per-claim memo of expensive answers, so each question is answered once (NFR-8)."""

    def __init__(self) -> None:
        """Open an empty memo for one claim."""

        self._answers: dict[str, object] = {}

        self._locks: dict[str, asyncio.Lock] = {}
        self._computed_count = 0

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[T]]) -> T:
        """Answer a question, doing the work only if this claim has not already done it."""

        if key in self._answers:
            logger.info("observation_reused", observation=key)
            return cast(T, self._answers[key])

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._answers:
                logger.info("observation_reused", observation=key)
                return cast(T, self._answers[key])

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
