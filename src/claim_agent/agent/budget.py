"""The bounds one investigation run works inside, so that it always stops (FR-1.3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.observability import get_logger
from claim_agent.policy import Policy

logger = get_logger(__name__)


class BudgetLimit(StrEnum):
    """A bound a whole run can reach, named the way a report refers to it."""

    STEPS = "steps"
    IMAGE_ANALYSES = "image_analyses"


class BudgetSnapshot(BaseModel):
    """What one run spent, in a form that can go straight into its report (NFR-3)."""

    model_config = ConfigDict(frozen=True)

    steps_used: int
    steps_allowed: int
    image_analyses_used: int
    image_analyses_allowed: int
    tool_retries_used: int
    tool_retries_allowed_per_call: int
    limits_reached: tuple[BudgetLimit, ...]


class RunBudget:
    """The step, retry and image allowance for exactly one investigation run (FR-1.3)."""

    def __init__(self, policy: Policy) -> None:
        """Open a fresh budget for one run, taking its three limits from the policy."""
        self._steps_allowed = policy.max_agent_steps
        self._image_analyses_allowed = policy.max_image_analyses_per_run
        self._retries_allowed_per_call = policy.max_tool_retries

        self._steps_used = 0
        self._image_analyses_used = 0
        # Keyed by the caller's id for one tool call: two calls in the same run must
        # not share an allowance. The run total is kept alongside it for the report.
        self._retries_used_by_call: dict[str, int] = {}
        self._retries_used = 0

    def has_step_left(self) -> bool:
        """Say whether the run may take another turn."""
        return self._steps_used < self._steps_allowed

    def has_image_analysis_left(self) -> bool:
        """Say whether the run may look at another photograph (NFR-8)."""
        return self._image_analyses_used < self._image_analyses_allowed

    def has_retry_left(self, tool_call_id: str) -> bool:
        """Say whether one failed tool call may be tried again."""
        return self._retries_used_by_call.get(tool_call_id, 0) < self._retries_allowed_per_call

    def limits_reached(self) -> tuple[BudgetLimit, ...]:
        """Name every whole-run bound this budget has reached, in a fixed order."""
        reached = []
        if not self.has_step_left():
            reached.append(BudgetLimit.STEPS)
        if not self.has_image_analysis_left():
            reached.append(BudgetLimit.IMAGE_ANALYSES)
        return tuple(reached)

    def spend_step(self) -> None:
        """Count one turn of the investigation against the step allowance."""
        if not self.has_step_left():
            raise RuntimeError(
                "The run tried to take a step after its step allowance ran out. "
                "Ask has_step_left() before every step."
            )
        self._steps_used += 1
        # Logged the moment the last step is spent, so this line appears once per
        # run at most. A run regularly reaching its ceiling means the ceiling is
        # wrong, and that is only visible if it is recorded.
        if not self.has_step_left():
            logger.info("run_step_budget_used_up", steps_allowed=self._steps_allowed)

    def spend_image_analysis(self) -> None:
        """Count one photograph against the image allowance (NFR-8)."""
        if not self.has_image_analysis_left():
            raise RuntimeError(
                "The run tried to analyse an image after its image allowance ran out. "
                "Ask has_image_analysis_left() before every image."
            )
        self._image_analyses_used += 1
        # Once per run at most. A run that keeps hitting this ceiling is being asked to
        # look at more evidence than we allow, and a representative sees a clarification
        # request without knowing why unless it is recorded.
        if not self.has_image_analysis_left():
            logger.info(
                "run_image_budget_used_up", image_analyses_allowed=self._image_analyses_allowed
            )

    def spend_retry(self, tool_call_id: str) -> None:
        """Count one more attempt at a tool call that has already failed."""
        if not self.has_retry_left(tool_call_id):
            raise RuntimeError(
                "The run tried to retry a tool call that had used up its retries. "
                "Ask has_retry_left() before every retry."
            )
        self._retries_used_by_call[tool_call_id] = (
            self._retries_used_by_call.get(tool_call_id, 0) + 1
        )
        self._retries_used += 1

    def snapshot(self) -> BudgetSnapshot:
        """Take an unchanging record of what has been spent so far (NFR-3)."""
        return BudgetSnapshot(
            steps_used=self._steps_used,
            steps_allowed=self._steps_allowed,
            image_analyses_used=self._image_analyses_used,
            image_analyses_allowed=self._image_analyses_allowed,
            tool_retries_used=self._retries_used,
            tool_retries_allowed_per_call=self._retries_allowed_per_call,
            limits_reached=self.limits_reached(),
        )
