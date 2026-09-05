"""The bounds one investigation run works inside, so that it always stops (FR-1.3).

The investigation decides for itself what to look at next, which means nothing in
its own reasoning promises it will ever finish. This file is that promise, kept
deliberately outside the reasoning: a plain counter the run has to ask before it
does anything, and which no amount of model output can talk its way past.

Three things are counted, because three things can run away:

* **Steps** — one turn of the investigation: pick a tool, use it, look at the
  result. Reaching the step limit is not a fault to crash on. It is an answer:
  the run stops and is sent for representative clarification to a support representative, carrying whatever
  it had already established, so nobody is handed an empty result (FR-1.16).
* **Retries** — how many more times one individual tool call may be tried after
  it fails. Counted per call rather than per run, so a flaky read early on cannot
  quietly eat the allowance of a later one.
* **Image analyses** — how many photographs one run may look at. Looking at an
  image is the most expensive thing this system does, so it has a ceiling of its
  own that a generous step allowance cannot lift (NFR-8).

**One budget object per run, always.** REQUIREMENTS.md is explicit that budgets
are per run, so a claim covering four products gets four budgets rather than one
shared between them (FR-1.3). Two things keep that from going wrong: there is no
shared instance anywhere and nothing here is cached, so the only way to get a
budget is to build one; and there is deliberately no way to reset or top up a
budget, so a used one cannot be recycled into a second run. Build a fresh
`RunBudget` as the first act of every run.

**Asking is separate from spending, on purpose.** A run *asks* whether it has
budget left and treats "no" as a reason to wrap up and request representative clarification — that is what
FR-1.16 describes, and it is why exhaustion is polled rather than thrown.
*Spending* past a limit, on the other hand, means the loop forgot to ask, which
is a bug in our code rather than an outcome for the claim, so it raises loudly
instead of letting the run overrun in silence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.observability import get_logger
from claim_agent.policy import Policy

logger = get_logger(__name__)


class BudgetLimit(StrEnum):
    """A bound a whole run can reach, named the way a report refers to it.

    Retries are absent from this list on purpose. They are counted per
    individual tool call, so "the retries are used up" is a fact about one call
    that has just failed, not a state the run as a whole is in.
    """

    STEPS = "steps"
    IMAGE_ANALYSES = "image_analyses"


class BudgetSnapshot(BaseModel):
    """What one run spent, in a form that can go straight into its report (NFR-3).

    A representative asked to accept an representative clarification request needs to see why it stopped,
    and "9 of 12 steps used" answers that without anyone reading logs. Every
    figure here is a count, so this is safe to send back over the API: it holds
    nothing a caller should not see.

    Frozen, so a snapshot cannot be edited after the fact and stops being a
    record of what happened.

    `limits_reached` is worked out from the counts at the moment the snapshot was
    taken. It is written down beside them rather than left to the reader to
    infer, because the whole point of the record is that nobody has to do
    arithmetic to find out why a claim was sent for representative clarification. It is empty while the run
    still had room, and can name both bounds when a run reached both.
    """

    model_config = ConfigDict(frozen=True)

    steps_used: int
    steps_allowed: int
    image_analyses_used: int
    image_analyses_allowed: int
    tool_retries_used: int
    tool_retries_allowed_per_call: int
    limits_reached: tuple[BudgetLimit, ...]


class RunBudget:
    """The step, retry and image allowance for exactly one investigation run (FR-1.3).

    Build one at the start of a run and let it be thrown away with the run. It is
    not thread-safe and is not meant to be: it belongs to one run, and one run
    does one thing at a time.

    The three limits come from the claim policy, which is the one named place
    judgement calls live so they can be changed without touching this code
    (FR-0.7, NFR-7). The policy is passed in rather than looked up here, so a
    test can set a limit to two and a run in progress cannot see a limit change
    underneath it.

    Every count starts at zero. A limit of zero retries is allowed and means a
    failed tool call is simply a failed tool call.
    """

    def __init__(self, policy: Policy) -> None:
        """Open a fresh budget for one run, taking its three limits from the policy."""
        self._steps_allowed = policy.max_agent_steps
        self._image_analyses_allowed = policy.max_image_analyses_per_run
        self._retries_allowed_per_call = policy.max_tool_retries

        self._steps_used = 0
        self._image_analyses_used = 0
        # Keyed by the caller's id for one tool call, because two tool calls in
        # the same run must not share an allowance. The run total is kept
        # alongside it purely for the report; adding up the values here would
        # give the same number, and a report should not have to.
        self._retries_used_by_call: dict[str, int] = {}
        self._retries_used = 0

    def has_step_left(self) -> bool:
        """Say whether the run may take another turn.

        This is the investigation's carry-on-or-stop question, asked before every
        step. A `False` here is the signal to wrap up and request representative clarification with what has
        been established so far, not to raise anything (FR-1.16).
        """
        return self._steps_used < self._steps_allowed

    def has_image_analysis_left(self) -> bool:
        """Say whether the run may look at another photograph (NFR-8).

        Independent of the step allowance: a run can be out of images while it
        still has steps left, and should then spend those steps drawing its
        conclusion rather than trying to look at more evidence.
        """
        return self._image_analyses_used < self._image_analyses_allowed

    def has_retry_left(self, tool_call_id: str) -> bool:
        """Say whether one failed tool call may be tried again.

        `tool_call_id` identifies the individual call, not the tool: two uses of
        the same tool in one run each get the full allowance, and reusing an id
        would wrongly make them share one. Any stable string will do — the id the
        model gave the call is the obvious choice.

        An id never seen before has its whole allowance, which is what makes the
        first failure of a call answerable without registering it first.
        """
        return self._retries_used_by_call.get(tool_call_id, 0) < self._retries_allowed_per_call

    def limits_reached(self) -> tuple[BudgetLimit, ...]:
        """Name every whole-run bound this budget has reached, in a fixed order.

        Empty while the run still has room everywhere. Used to explain an
        representative clarification request, so the order is fixed rather than dependent on which bound
        was hit first — the same pair of exhausted limits always reads the same
        way (NFR-1).
        """
        reached = []
        if not self.has_step_left():
            reached.append(BudgetLimit.STEPS)
        if not self.has_image_analysis_left():
            reached.append(BudgetLimit.IMAGE_ANALYSES)
        return tuple(reached)

    def spend_step(self) -> None:
        """Count one turn of the investigation against the step allowance.

        Raises:
            RuntimeError: the allowance was already used up. That means the loop
                did not ask `has_step_left` first, which is a mistake in our own
                code rather than something that happened to the claim — so it is
                not one of the handled errors in `claim_agent.errors`, and it is
                raised rather than absorbed so that an overrun can never pass
                unnoticed.
        """
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
        """Count one photograph against the image allowance (NFR-8).

        This does not also count a step. A step is one turn of the
        investigation and an image analysis is one thing a turn can do, so the
        caller spends both.

        Raises:
            RuntimeError: the image allowance was already used up, meaning
                `has_image_analysis_left` was not asked first. Treated exactly
                like an overrun of the step allowance, and for the same reason.
        """
        if not self.has_image_analysis_left():
            raise RuntimeError(
                "The run tried to analyse an image after its image allowance ran out. "
                "Ask has_image_analysis_left() before every image."
            )
        self._image_analyses_used += 1
        # Once per run at most, for the same reason as the step allowance: a run
        # that keeps hitting this ceiling is being asked to look at more evidence
        # than we let it, and a representative will see an representative clarification request without
        # knowing why unless it is recorded.
        if not self.has_image_analysis_left():
            logger.info(
                "run_image_budget_used_up", image_analyses_allowed=self._image_analyses_allowed
            )

    def spend_retry(self, tool_call_id: str) -> None:
        """Count one more attempt at a tool call that has already failed.

        Raises:
            RuntimeError: this call's retries were already used up, meaning
                `has_retry_left` was not asked first. Treated exactly like an
                overrun of the step allowance, and for the same reason.
        """
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
        """Take an unchanging record of what has been spent so far (NFR-3).

        Safe to call at any point and as often as wanted: it reads the counts,
        changes nothing, and writes nothing to the logs. Take one when the run
        ends and put it in the report, so a representative can see what the run
        cost and whether it stopped because it ran out of room.
        """
        return BudgetSnapshot(
            steps_used=self._steps_used,
            steps_allowed=self._steps_allowed,
            image_analyses_used=self._image_analyses_used,
            image_analyses_allowed=self._image_analyses_allowed,
            tool_retries_used=self._retries_used,
            tool_retries_allowed_per_call=self._retries_allowed_per_call,
            limits_reached=self.limits_reached(),
        )
