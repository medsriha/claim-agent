"""Remembering an expensive answer, so one claim never pays for it twice (NFR-8).

Looking at a photograph is the most expensive thing this system does. A claim can cover
several damaged products, and the products are investigated alongside each other, so the
same photograph — the picture of the box the order arrived in, the photographed invoice,
the customer's screenshot — is the kind of thing several of those investigations want to
ask about. Asking about it once per product would multiply the cost of a claim by the
number of things that were broken, for no better answer.

This is the memo that stops that. The first caller to ask a question does the work; every
later caller in the same claim is handed what the first one found.

**One memo per claim, never a shared one.** The whole point is that a claim's answers
belong to that claim: two different claims are two different sets of photographs and must
never see each other's conclusions, and a memo that outlived a claim would hand a stale
answer to a later one. So there is deliberately no shared instance in this module and
nothing here is cached — the only way to get a memo is to build one, and it is thrown
away with the claim that built it. This mirrors the run budget in `budget.py`, which is
built fresh for the same reason.

**Nothing here decides anything.** It remembers answers and hands them back. What the
questions are, and what the answers mean for a claim, live elsewhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from claim_agent.observability import get_logger

logger = get_logger(__name__)

# The kind of answer being remembered. The memo does not care what an answer is — it
# never looks inside one — so this is deliberately unrestricted, and naming it is what
# lets a caller get back exactly the type it asked for rather than something it has to
# check.
T = TypeVar("T")


class ObservationCache:
    """A per-claim memo of expensive answers, so each question is answered once (NFR-8).

    Build one at the start of a claim and let it be thrown away with the claim. It is
    for one claim's questions only — see this module's opening note on why it is never
    shared.

    Safe to use from several investigations running at once, which is the case it exists
    for: if two of them ask the same question at the same moment, the work happens once
    and both are given that one answer.

    It is not thread-safe, and does not need to be. Everything in a claim runs on one
    event loop.
    """

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
        """Answer a question, doing the work only if this claim has not already done it.

        The first caller for a key runs `compute` and its answer is kept. Anyone else
        asking the same key in the same claim gets that answer back without the work
        being repeated — including a caller that arrived while the first one was still
        working, who waits for it rather than starting a second copy. The result cannot
        depend on which of them got there first, which is what makes a claim's outcome
        repeatable when its lines are investigated at the same time.

        A `compute` that raises is **not** remembered. The failure is passed straight to
        the caller who asked, and the next caller starts again from nothing — a moment of
        trouble must not become this claim's permanent answer to the question.

        Args:
            key: Names the question, and must name it completely. Two questions that
                could give different answers must never share a key, because the second
                one would silently be given the first one's answer. Something like
                "damage-visible:ATT-CASE-1003-01" is the shape to aim for.
            compute: What to do if the answer is not already known. Called with no
                arguments, at most once per key.

        Returns:
            The answer, whether it was just worked out or already known. `None` is a
            perfectly good answer and is remembered like any other.

        Raises:
            Whatever `compute` raises, unchanged, and without remembering it.
        """
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
        """Name every question this claim has an answer for, oldest first.

        Held to the order the answers arrived in so a report of what a claim looked at
        reads the same way twice. A question whose work failed is absent, because nothing
        was remembered for it.
        """
        return tuple(self._answers)

    @property
    def computed_count(self) -> int:
        """How many times the expensive work was actually started for this claim.

        A failed attempt counts, because it cost what a successful one costs. Compare it
        with the number of times a caller asked to see how much the memo saved (NFR-8).
        """
        return self._computed_count
