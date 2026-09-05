"""The bounds that stop an investigation running forever (FR-1.3, FR-1.16).

The budget is a plain counter over numbers that have already been read, so these
tests build a policy directly and call it. Nothing reaches the network, no model
is involved, and no stand-in API is needed.

The limits used here are small ones of our own, not the policy defaults, so that
a test can spend a whole allowance in three lines and say plainly what it is
about. Where a default matters, the test says which default it means.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claim_agent.agent.budget import BudgetLimit, RunBudget
from claim_agent.policy import Policy


def budget_of(*, steps: int = 3, images: int = 2, retries: int = 1) -> RunBudget:
    """A fresh budget with small limits, so a test can use one up quickly."""
    return RunBudget(
        Policy(
            max_agent_steps=steps,
            max_image_analyses_per_run=images,
            max_tool_retries=retries,
        )
    )


def test_a_new_budget_has_its_whole_allowance() -> None:
    """FR-1.3: a run starts with room for everything its policy allows."""
    budget = budget_of(steps=3, images=2, retries=1)

    assert budget.has_step_left() is True
    assert budget.has_image_analysis_left() is True
    assert budget.has_retry_left("call-1") is True
    assert budget.limits_reached() == ()
    assert budget.snapshot().steps_used == 0


def test_the_limits_come_from_the_policy_and_not_from_this_code() -> None:
    """FR-0.7, NFR-7: the three bounds are policy values, changeable without a code change."""
    snapshot = RunBudget(
        Policy(max_agent_steps=7, max_image_analyses_per_run=4, max_tool_retries=5)
    ).snapshot()

    assert snapshot.steps_allowed == 7
    assert snapshot.image_analyses_allowed == 4
    assert snapshot.tool_retries_allowed_per_call == 5


def test_a_run_may_take_exactly_as_many_steps_as_it_is_allowed() -> None:
    """FR-1.3: the last permitted step is permitted, and the allowance is then gone."""
    budget = budget_of(steps=3)

    for _ in range(3):
        assert budget.has_step_left() is True
        budget.spend_step()

    assert budget.has_step_left() is False
    assert budget.snapshot().steps_used == 3


def test_running_out_of_steps_is_an_answer_rather_than_a_failure() -> None:
    """FR-1.16: exhaustion is something the run asks about, so it can request representative clarification with what it has."""
    budget = budget_of(steps=1)

    budget.spend_step()

    # Nothing was raised by spending the last step. The run finds out by asking,
    # which is what lets it carry its findings forward instead of losing them.
    assert budget.has_step_left() is False
    assert budget.limits_reached() == (BudgetLimit.STEPS,)


def test_stepping_one_past_the_limit_is_refused_rather_than_allowed_quietly() -> None:
    """FR-1.3: an overrun cannot happen in silence, because the loop forgot to ask."""
    budget = budget_of(steps=1)
    budget.spend_step()

    with pytest.raises(RuntimeError, match="step allowance"):
        budget.spend_step()

    # The refused step was not counted, so the record still says what really happened.
    assert budget.snapshot().steps_used == 1


def test_each_tool_call_gets_its_own_retries() -> None:
    """FR-1.3: retries are counted per call, so one flaky read cannot spend another's allowance."""
    budget = budget_of(retries=1)

    budget.spend_retry("call-1")

    assert budget.has_retry_left("call-1") is False
    assert budget.has_retry_left("call-2") is True


def test_a_tool_call_that_has_used_its_retries_cannot_be_retried_again() -> None:
    """FR-1.3: bounded retries — the second refusal is loud, not quiet."""
    budget = budget_of(retries=2)

    budget.spend_retry("call-1")
    budget.spend_retry("call-1")

    assert budget.has_retry_left("call-1") is False
    with pytest.raises(RuntimeError, match="retries"):
        budget.spend_retry("call-1")


def test_a_policy_of_no_retries_means_a_failed_tool_call_is_simply_failed() -> None:
    """FR-1.3: zero is a valid allowance, and the budget does not quietly grant one anyway."""
    budget = budget_of(retries=0)

    assert budget.has_retry_left("call-1") is False
    with pytest.raises(RuntimeError, match="retries"):
        budget.spend_retry("call-1")


def test_the_image_ceiling_can_be_reached_while_steps_are_still_left() -> None:
    """NFR-8: looking at images has a ceiling of its own that a step allowance cannot lift."""
    budget = budget_of(steps=10, images=2)

    budget.spend_image_analysis()
    budget.spend_image_analysis()

    assert budget.has_image_analysis_left() is False
    # The run is not over: it should spend its remaining steps drawing a
    # conclusion from what it has already seen.
    assert budget.has_step_left() is True
    assert budget.limits_reached() == (BudgetLimit.IMAGE_ANALYSES,)


def test_looking_at_one_more_image_than_allowed_is_refused() -> None:
    """NFR-8: the image ceiling is enforced, not advisory."""
    budget = budget_of(images=1)
    budget.spend_image_analysis()

    with pytest.raises(RuntimeError, match="image allowance"):
        budget.spend_image_analysis()

    assert budget.snapshot().image_analyses_used == 1


def test_analysing_an_image_does_not_also_spend_a_step() -> None:
    """FR-1.3, NFR-8: the two allowances are counted separately, so a caller spends both."""
    budget = budget_of(steps=3, images=2)

    budget.spend_image_analysis()

    assert budget.snapshot().steps_used == 0
    assert budget.snapshot().image_analyses_used == 1


def test_a_run_that_reaches_both_ceilings_reports_both_in_a_fixed_order() -> None:
    """NFR-1, NFR-3: the same pair of exhausted limits always reads the same way."""
    budget = budget_of(steps=1, images=1)

    budget.spend_image_analysis()
    budget.spend_step()

    assert budget.limits_reached() == (BudgetLimit.STEPS, BudgetLimit.IMAGE_ANALYSES)


def test_the_snapshot_says_what_a_representative_needs_to_see() -> None:
    """NFR-3: "9 of 12 steps used" is answerable from the report, without reading logs."""
    budget = RunBudget(
        Policy(max_agent_steps=12, max_image_analyses_per_run=20, max_tool_retries=2)
    )
    for _ in range(9):
        budget.spend_step()
    budget.spend_image_analysis()
    budget.spend_retry("call-1")

    snapshot = budget.snapshot()

    assert (snapshot.steps_used, snapshot.steps_allowed) == (9, 12)
    assert (snapshot.image_analyses_used, snapshot.image_analyses_allowed) == (1, 20)
    assert snapshot.tool_retries_used == 1
    assert snapshot.limits_reached == ()


def test_the_snapshot_counts_retries_across_the_whole_run() -> None:
    """NFR-3: the report says how much retrying a run did, without anyone adding it up."""
    budget = budget_of(retries=2)

    budget.spend_retry("call-1")
    budget.spend_retry("call-1")
    budget.spend_retry("call-2")

    assert budget.snapshot().tool_retries_used == 3


def test_a_snapshot_cannot_be_edited_after_it_is_taken() -> None:
    """NFR-3, NFR-5: a record that can be rewritten is not a record."""
    snapshot = budget_of().snapshot()

    with pytest.raises(ValidationError):
        snapshot.steps_used = 99  # type: ignore[misc]


def test_taking_a_snapshot_does_not_change_the_budget() -> None:
    """NFR-3: reading the record is safe to do as often as a caller likes."""
    budget = budget_of(steps=3)
    budget.spend_step()

    budget.snapshot()
    budget.snapshot()

    assert budget.snapshot().steps_used == 1
    assert budget.has_step_left() is True


def test_every_run_gets_its_own_budget() -> None:
    """FR-1.3: budgets are per run, so a claim with several lines does not share one."""
    policy = Policy(max_agent_steps=1, max_image_analyses_per_run=1, max_tool_retries=1)

    first_line = RunBudget(policy)
    second_line = RunBudget(policy)
    first_line.spend_step()

    # The second line's run starts with its whole allowance, even though the
    # first line's run has already used all of its own.
    assert first_line.has_step_left() is False
    assert second_line.has_step_left() is True
    assert second_line.snapshot().steps_used == 0


def test_a_used_budget_cannot_be_topped_up_or_started_again() -> None:
    """FR-1.3: there is deliberately no way to recycle a budget into a second run."""
    budget = budget_of(steps=1)

    assert not hasattr(budget, "reset")
    assert not hasattr(budget, "clear")
    assert not hasattr(budget, "extend")
