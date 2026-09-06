from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from claim_agent.agent.budget import BudgetLimit, RunBudget
from claim_agent.policy import Policy


def budget_of(*, steps: int = 3, images: int = 2) -> RunBudget:
    return RunBudget(Policy(max_agent_steps=steps, max_image_analyses_per_run=images))


def test_a_new_budget_has_its_whole_allowance() -> None:
    budget = budget_of(steps=3, images=2)

    assert budget.has_step_left() is True
    assert budget.has_image_analysis_left() is True
    assert budget.limits_reached() == ()
    assert budget.snapshot().steps_used == 0


def test_the_limits_come_from_the_policy_and_not_from_this_code() -> None:
    budget = RunBudget(
        Policy(max_agent_steps=7, max_image_analyses_per_run=4, max_tool_calls_per_step=3)
    )
    snapshot = budget.snapshot()

    assert snapshot.steps_allowed == 7
    assert snapshot.image_analyses_allowed == 4
    assert budget.tool_calls_allowed_per_step == 3


def test_a_run_may_take_exactly_as_many_steps_as_it_is_allowed() -> None:
    budget = budget_of(steps=3)

    for _ in range(3):
        assert budget.has_step_left() is True
        budget.spend_step()

    assert budget.has_step_left() is False
    assert budget.snapshot().steps_used == 3


def test_running_out_of_steps_is_an_answer_rather_than_a_failure() -> None:
    budget = budget_of(steps=1)

    budget.spend_step()

    assert budget.has_step_left() is False
    assert budget.limits_reached() == (BudgetLimit.STEPS,)


def test_stepping_one_past_the_limit_is_refused_rather_than_allowed_quietly() -> None:
    budget = budget_of(steps=1)
    budget.spend_step()

    with pytest.raises(RuntimeError, match="step allowance"):
        budget.spend_step()

    assert budget.snapshot().steps_used == 1


def test_the_image_ceiling_can_be_reached_while_steps_are_still_left() -> None:
    budget = budget_of(steps=10, images=2)

    budget.spend_image_analysis()
    budget.spend_image_analysis()

    assert budget.has_image_analysis_left() is False

    assert budget.has_step_left() is True
    assert budget.limits_reached() == (BudgetLimit.IMAGE_ANALYSES,)


def test_looking_at_one_more_image_than_allowed_is_refused() -> None:
    budget = budget_of(images=1)
    budget.spend_image_analysis()

    with pytest.raises(RuntimeError, match="image allowance"):
        budget.spend_image_analysis()

    assert budget.snapshot().image_analyses_used == 1


def test_analysing_an_image_does_not_also_spend_a_step() -> None:
    budget = budget_of(steps=3, images=2)

    budget.spend_image_analysis()

    assert budget.snapshot().steps_used == 0
    assert budget.snapshot().image_analyses_used == 1


def test_a_run_that_reaches_both_ceilings_reports_both_in_a_fixed_order() -> None:
    budget = budget_of(steps=1, images=1)

    budget.spend_image_analysis()
    budget.spend_step()

    assert budget.limits_reached() == (BudgetLimit.STEPS, BudgetLimit.IMAGE_ANALYSES)


def test_the_snapshot_says_what_a_representative_needs_to_see() -> None:
    budget = RunBudget(Policy(max_agent_steps=12, max_image_analyses_per_run=20))
    for _ in range(9):
        budget.spend_step()
    budget.spend_image_analysis()
    budget.record_usage(
        {"input_tokens": 1200, "output_tokens": 80, "input_token_details": {"cache_read": 1000}}
    )
    budget.record_usage(None)

    snapshot = budget.snapshot()

    assert (snapshot.steps_used, snapshot.steps_allowed) == (9, 12)
    assert (snapshot.image_analyses_used, snapshot.image_analyses_allowed) == (1, 20)
    assert snapshot.limits_reached == ()

    assert snapshot.model_calls == 2
    assert (snapshot.input_tokens, snapshot.output_tokens, snapshot.cache_read_tokens) == (
        1200,
        80,
        1000,
    )


def test_a_snapshot_cannot_be_edited_after_it_is_taken() -> None:
    snapshot = budget_of().snapshot()

    with pytest.raises(ValidationError):
        cast(Any, snapshot).steps_used = 99


def test_taking_a_snapshot_does_not_change_the_budget() -> None:
    budget = budget_of(steps=3)
    budget.spend_step()

    budget.snapshot()
    budget.snapshot()

    assert budget.snapshot().steps_used == 1
    assert budget.has_step_left() is True


def test_every_run_gets_its_own_budget() -> None:
    policy = Policy(max_agent_steps=1, max_image_analyses_per_run=1)

    first_line = RunBudget(policy)
    second_line = RunBudget(policy)
    first_line.spend_step()

    assert first_line.has_step_left() is False
    assert second_line.has_step_left() is True
    assert second_line.snapshot().steps_used == 0


def test_a_used_budget_cannot_be_topped_up_or_started_again() -> None:
    budget = budget_of(steps=1)

    assert not hasattr(budget, "reset")
    assert not hasattr(budget, "clear")
    assert not hasattr(budget, "extend")
