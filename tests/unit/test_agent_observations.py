from __future__ import annotations

import asyncio

import pytest

from claim_agent.agent.observations import ObservationCache


async def test_asking_the_same_question_twice_does_the_work_once() -> None:
    """NFR-8: image analysis must not be repeated for the same attachment within a case."""
    cache = ObservationCache()
    runs = 0

    async def look_at_the_photograph() -> str:
        nonlocal runs
        runs += 1
        return "the box is crushed"

    first = await cache.get_or_compute("damage:ATT-1", look_at_the_photograph)
    second = await cache.get_or_compute("damage:ATT-1", look_at_the_photograph)

    assert first == "the box is crushed"
    assert second == first
    assert runs == 1
    assert cache.computed_count == 1


async def test_two_questions_are_two_pieces_of_work() -> None:
    """NFR-8: the memo saves repeated work, and must never merge two different questions."""
    cache = ObservationCache()

    async def answer_about(photograph: str) -> str:
        return f"looked at {photograph}"

    first = await cache.get_or_compute("damage:ATT-1", lambda: answer_about("ATT-1"))
    second = await cache.get_or_compute("damage:ATT-2", lambda: answer_about("ATT-2"))

    assert first == "looked at ATT-1"
    assert second == "looked at ATT-2"
    assert cache.computed_count == 2
    assert cache.keys() == ("damage:ATT-1", "damage:ATT-2")


async def test_two_callers_at_the_same_moment_share_one_answer() -> None:
    """NFR-8: a claim's lines are investigated alongside each other and must not both pay."""
    cache = ObservationCache()
    runs = 0
    work_started = asyncio.Event()
    let_the_work_finish = asyncio.Event()

    async def look_at_the_photograph() -> str:
        nonlocal runs
        runs += 1
        work_started.set()
        await let_the_work_finish.wait()
        return "the box is crushed"

    first_line = asyncio.create_task(cache.get_or_compute("damage:ATT-1", look_at_the_photograph))
    await work_started.wait()
    # The second claim line asks while the first is still waiting for its answer.
    second_line = asyncio.create_task(cache.get_or_compute("damage:ATT-1", look_at_the_photograph))
    # Give the second line a turn, so it is queued behind the first rather than not started.
    await asyncio.sleep(0)
    let_the_work_finish.set()

    assert await first_line == "the box is crushed"
    assert await second_line == "the box is crushed"
    assert runs == 1
    assert cache.computed_count == 1


async def test_two_different_questions_do_not_wait_for_each_other() -> None:
    """NFR-8: the memo saves work; it must not turn a claim's lines into a queue."""
    cache = ObservationCache()
    both_started = asyncio.Event()
    started = 0

    async def look_until_the_other_starts_too() -> str:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        # Neither answer can be given until the other question has also been started, so
        # this only finishes if the two ran alongside each other.
        await both_started.wait()
        return "looked"

    answers = await asyncio.gather(
        cache.get_or_compute("damage:ATT-1", look_until_the_other_starts_too),
        cache.get_or_compute("damage:ATT-2", look_until_the_other_starts_too),
    )

    assert list(answers) == ["looked", "looked"]
    assert cache.computed_count == 2


async def test_a_question_whose_work_failed_is_not_remembered() -> None:
    """NFR-4: a moment of trouble must not become this claim's permanent answer."""
    cache = ObservationCache()

    async def fail() -> str:
        raise RuntimeError("the model did not answer in time")

    async def succeed() -> str:
        return "the box is crushed"

    with pytest.raises(RuntimeError):
        await cache.get_or_compute("damage:ATT-1", fail)

    assert cache.keys() == ()

    # The next caller starts again from nothing rather than being handed the failure.
    assert await cache.get_or_compute("damage:ATT-1", succeed) == "the box is crushed"
    assert cache.keys() == ("damage:ATT-1",)
    # Two attempts were made, and both cost what an attempt costs.
    assert cache.computed_count == 2


async def test_the_failure_reaches_the_caller_that_asked() -> None:
    """NFR-4: an expensive answer that could not be worked out fails plainly, never quietly."""
    cache = ObservationCache()

    async def fail() -> str:
        raise RuntimeError("the model did not answer in time")

    with pytest.raises(RuntimeError, match="did not answer in time"):
        await cache.get_or_compute("damage:ATT-1", fail)


async def test_an_answer_of_nothing_is_still_an_answer() -> None:
    """NFR-8: "there is nothing to report" costs the same to work out, so it is remembered too."""
    cache = ObservationCache()
    runs = 0

    async def find_nothing() -> str | None:
        nonlocal runs
        runs += 1
        return None

    assert await cache.get_or_compute("damage:ATT-1", find_nothing) is None
    assert await cache.get_or_compute("damage:ATT-1", find_nothing) is None
    assert runs == 1


async def test_a_memo_belongs_to_one_claim_only() -> None:
    """NFR-8: two claims are two sets of photographs and must never see each other's answers."""
    one_claim = ObservationCache()
    another_claim = ObservationCache()

    async def answer_for(claim: str) -> str:
        return f"looked at {claim}'s photograph"

    first = await one_claim.get_or_compute("damage:ATT-1", lambda: answer_for("CASE-1001"))
    second = await another_claim.get_or_compute("damage:ATT-1", lambda: answer_for("CASE-1003"))

    assert first == "looked at CASE-1001's photograph"
    assert second == "looked at CASE-1003's photograph"
    assert one_claim.computed_count == 1
    assert another_claim.computed_count == 1


async def test_a_new_memo_has_nothing_in_it() -> None:
    """NFR-8: a fresh memo is what every claim starts with, and it remembers nothing."""
    cache = ObservationCache()

    assert cache.keys() == ()
    assert cache.computed_count == 0
