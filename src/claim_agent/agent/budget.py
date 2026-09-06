from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult
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
    limits_reached: tuple[BudgetLimit, ...]
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class RunBudget:
    """The step and image allowance for exactly one run, and what the run has cost (FR-1.3)."""

    def __init__(self, policy: Policy) -> None:
        """Open a fresh budget for one run, taking its limits from the policy."""
        self._steps_allowed = policy.max_agent_steps
        self._image_analyses_allowed = policy.max_image_analyses_per_run
        self._tool_calls_allowed_per_step = policy.max_tool_calls_per_step

        self._steps_used = 0
        self._image_analyses_used = 0
        self._model_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0

    @property
    def tool_calls_allowed_per_step(self) -> int:
        """How many tools one turn may ask for at once (FR-1.3)."""
        return self._tool_calls_allowed_per_step

    def has_step_left(self) -> bool:
        """Say whether the run may take another turn."""
        return self._steps_used < self._steps_allowed

    def has_image_analysis_left(self) -> bool:
        """Say whether the run may look at another photograph (NFR-8)."""
        return self._image_analyses_used < self._image_analyses_allowed

    def limits_reached(self) -> tuple[BudgetLimit, ...]:
        """Name every whole-run bound this budget has reached, in a fixed order."""
        reached = []
        if not self.has_step_left():
            reached.append(BudgetLimit.STEPS)
        if not self.has_image_analysis_left():
            reached.append(BudgetLimit.IMAGE_ANALYSES)
        return tuple(reached)

    def spend_step(self) -> None:
        """Count one turn against the step allowance."""
        if not self.has_step_left():
            raise RuntimeError(
                "The run tried to take a step after its step allowance ran out. "
                "Ask has_step_left() before every step."
            )
        self._steps_used += 1
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
        if not self.has_image_analysis_left():
            logger.info(
                "run_image_budget_used_up", image_analyses_allowed=self._image_analyses_allowed
            )

    def try_spend_image_analysis(self) -> bool:
        """Check and spend in one move, so concurrent inspections cannot both pass one check."""
        if not self.has_image_analysis_left():
            return False
        self.spend_image_analysis()
        return True

    def record_usage(self, usage: Mapping[str, Any] | None) -> None:
        """Add what the provider reported for one model call to the run's total."""
        self._model_calls += 1
        if not usage:
            return
        self._input_tokens += int(usage.get("input_tokens", 0) or 0)
        self._output_tokens += int(usage.get("output_tokens", 0) or 0)
        details = usage.get("input_token_details") or {}
        self._cache_read_tokens += int(details.get("cache_read", 0) or 0)

    def snapshot(self) -> BudgetSnapshot:
        """Take an unchanging record of what has been spent so far (NFR-3)."""
        return BudgetSnapshot(
            steps_used=self._steps_used,
            steps_allowed=self._steps_allowed,
            image_analyses_used=self._image_analyses_used,
            image_analyses_allowed=self._image_analyses_allowed,
            limits_reached=self.limits_reached(),
            model_calls=self._model_calls,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_read_tokens=self._cache_read_tokens,
        )


class UsageMeter(AsyncCallbackHandler):
    """A callback that hands each model reply's usage to a recorder."""

    def __init__(self, record: Callable[[Mapping[str, Any] | None], None]) -> None:
        """Forward every reply's usage to `record`."""
        self._record = record

    async def on_llm_end(self, response: LLMResult, **_unused: object) -> None:
        """Read the usage off the first generation, which is the only one a chat call has."""
        for generations in response.generations:
            for generation in generations:
                if isinstance(generation, ChatGeneration):
                    self._record(getattr(generation.message, "usage_metadata", None))
                    return
        self._record(None)
