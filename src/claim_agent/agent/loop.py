"""The tool-use loop every AI pass in this system runs inside (FR-1.1, FR-1.3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypedDict, TypeVar, cast

from langchain_core.exceptions import ModelError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from claim_agent.agent.budget import BudgetSnapshot, RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.ledger import LedgerEntry, RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.errors import UpstreamError
from claim_agent.observability import get_logger

logger = get_logger(__name__)

# The form this pass ends on — one of the shapes in `claim_agent.agent.schemas`.
# Naming it is what lets a caller that asked for a claim split get a claim split
# back, rather than something it has to check the type of itself.
Answer = TypeVar("Answer", bound=BaseModel)

# A backstop that must never be what stops a run: the graph ends a run by raising, and
# raising loses the findings FR-1.16 says must reach a person. Two graph moves per step
# — think, then act — plus a few for starting and concluding, so ours always trips first.
_MOVES_PER_STEP = 2
_MOVES_TO_SPARE = 10


def _graph_limit(budget: RunBudget) -> int:
    """Work out the graph's own limit, always looser than the step allowance."""
    return budget.snapshot().steps_allowed * _MOVES_PER_STEP + _MOVES_TO_SPARE


class _PassState(TypedDict):
    """What one pass carries between moves."""

    messages: list[BaseMessage]
    outcome: LoopOutcome[Any] | None


@dataclass(frozen=True)
class LoopOutcome(Generic[Answer]):
    """Everything one pass established, whether or not it reached a conclusion."""

    answer: Answer | None
    reason: str | None
    budget: BudgetSnapshot
    ledger: tuple[LedgerEntry, ...]

    @property
    def gave_up(self) -> bool:
        """Whether the pass stopped without reaching a conclusion."""
        return self.answer is None


async def run_agent_pass(
    *,
    opening_messages: Sequence[BaseMessage],
    tools: Sequence[BaseTool],
    concludes_with: type[Answer],
    closing_request: str,
    chat: BaseChatModel,
    structured: StructuredModel,
    budget: RunBudget,
    ledger: RunLedger,
    events: EventStream,
) -> LoopOutcome[Answer]:
    """Run one AI pass: ask, use tools, ask again, then conclude (FR-1.1, FR-1.3)."""
    _refuse_a_used_budget(budget)

    model = chat.bind_tools(list(tools))
    tools_by_name = {tool.name: tool for tool in tools}

    async def think(state: _PassState) -> dict[str, object]:
        """Ask the model what it wants to do next."""
        if not budget.has_step_left():
            snapshot = budget.snapshot()
            logger.info(
                "agent_pass_out_of_steps",
                form=concludes_with.__name__,
                steps_used=snapshot.steps_used,
            )
            return {
                "outcome": _gave_up(
                    f"The investigation used all {snapshot.steps_allowed} of the steps it "
                    "is allowed before it reached a conclusion.",
                    budget=budget,
                    ledger=ledger,
                )
            }

        budget.spend_step()

        try:
            reply = await model.ainvoke(state["messages"])
        except TimeoutError:
            return {
                "outcome": _model_turn_failed(
                    "The model provider did not answer in time.",
                    failure="TimeoutError",
                    concludes_with=concludes_with,
                    budget=budget,
                    ledger=ledger,
                )
            }
        except ModelError as exc:
            # Both end the pass — a turn is never retried — but they send a reader
            # looking in different places, so they are reported differently.
            return {
                "outcome": _model_turn_failed(
                    "The model provider could not be reached."
                    if exc.is_retryable
                    else "The model provider refused the request.",
                    failure=type(exc).__name__,
                    concludes_with=concludes_with,
                    budget=budget,
                    ledger=ledger,
                )
            }

        await _pass_on_what_the_model_said(reply, events=events)
        return {"messages": [*state["messages"], reply]}

    async def act(state: _PassState) -> dict[str, object]:
        """Carry out whatever the model just asked for, and hand back what came of it."""
        asked_for = state["messages"][-1]
        answers: list[BaseMessage] = [
            await _carry_out(
                tool_call,
                tools_by_name=tools_by_name,
                budget=budget,
                ledger=ledger,
                events=events,
            )
            for tool_call in cast(AIMessage, asked_for).tool_calls
        ]
        return {"messages": [*state["messages"], *answers]}

    async def conclude(state: _PassState) -> dict[str, object]:
        """Ask for the form this pass ends on, once the model has stopped looking."""
        return {
            "outcome": await _conclude(
                state["messages"],
                concludes_with=concludes_with,
                closing_request=closing_request,
                structured=structured,
                budget=budget,
                ledger=ledger,
            )
        }

    def what_next(state: _PassState) -> str:
        """Decide where the pass goes after the model has spoken."""
        if state["outcome"] is not None:
            return "done"
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "act"
        return "conclude"

    builder: StateGraph[_PassState, None, _PassState, _PassState] = StateGraph(_PassState)
    builder.add_node("think", think)
    builder.add_node("act", act)
    builder.add_node("conclude", conclude)
    builder.add_edge(START, "think")
    builder.add_conditional_edges(
        "think", what_next, {"act": "act", "conclude": "conclude", "done": END}
    )
    # Straight back to thinking, with no allowance check on the way. The check lives
    # at the top of `think` instead, so there is exactly one place that decides
    # whether a run may continue rather than two that could disagree.
    builder.add_edge("act", "think")
    builder.add_edge("conclude", END)

    finished = await builder.compile().ainvoke(
        {"messages": list(opening_messages), "outcome": None},
        config={"recursion_limit": _graph_limit(budget)},
    )

    outcome = finished["outcome"]
    if outcome is None:
        # Not reachable by any path above: every way out of the graph sets an
        # outcome. Kept because "the graph ended without an answer" must never
        # become a silent `None` in front of a rep (NFR-4).
        return _gave_up(
            "The investigation stopped without reaching a conclusion.",
            budget=budget,
            ledger=ledger,
        )
    return cast(LoopOutcome[Answer], outcome)


async def _conclude(
    messages: Sequence[BaseMessage],
    *,
    concludes_with: type[Answer],
    closing_request: str,
    structured: StructuredModel,
    budget: RunBudget,
    ledger: RunLedger,
) -> LoopOutcome[Answer]:
    """Ask the model to fill in the form this pass ends on (NFR-2)."""
    closing = [*messages, HumanMessage(content=closing_request)]
    asked = f"Draw a conclusion for this pass, in the shape of {concludes_with.__name__}."

    try:
        answer = await structured.ask(concludes_with, closing)
    except UpstreamError as exc:
        # `exc.message` is our own plain sentence, written for a person to read —
        # not the provider's wording — so it is safe to pass on as the reason.
        ledger.record(
            kind=StepKind.REASONING,
            name=concludes_with.__name__,
            asked=asked,
            observed=exc.message,
            succeeded=False,
        )
        logger.warning(
            "agent_conclusion_unusable",
            form=concludes_with.__name__,
        )
        return _gave_up(exc.message, budget=budget, ledger=ledger)

    ledger.record(
        kind=StepKind.REASONING,
        name=concludes_with.__name__,
        asked=asked,
        observed="The model filled the form in.",
        succeeded=True,
    )
    return LoopOutcome(
        answer=answer,
        reason=None,
        budget=budget.snapshot(),
        ledger=ledger.entries(),
    )


async def _carry_out(
    tool_call: ToolCall,
    *,
    tools_by_name: dict[str, BaseTool],
    budget: RunBudget,
    ledger: RunLedger,
    events: EventStream,
) -> ToolMessage:
    """Do the one thing the model asked for, and put the result into words for it."""
    # The model should always give a call an id, and the id it gives is the right
    # thing to count retries against. One made up from where the call appeared is
    # the fallback, because two calls must never share a retry allowance and an
    # absent id would make every call in the run look like the same one.
    call_id = tool_call["id"] or f"unnamed-call-{len(ledger) + 1}"
    name = tool_call["name"]
    asked = _what_was_asked_for(name, tool_call["args"])

    tool = tools_by_name.get(name)
    if tool is None:
        # Not retried: the same name will be missing the second time. The model is
        # told what it does have, which is enough for it to correct itself on the
        # next turn — and that turn costs a step, so this cannot go round for ever.
        available = ", ".join(sorted(tools_by_name)) or "no tools at all"
        refusal = f"There is no tool called {name}. The tools available are: {available}."
        ledger.record(
            kind=StepKind.TOOL_CALL,
            name=name,
            asked=asked,
            observed=refusal,
            succeeded=False,
        )
        await events.emit(
            EventKind.TOOL_CALLED,
            f"The investigation asked for a tool called {name}, which it does not have.",
            tool=name,
            outcome="unknown_tool",
        )
        return ToolMessage(content=refusal, tool_call_id=call_id, name=name, status="error")

    # Noted before the call so we can tell afterwards whether the tool wrote its own
    # record. A tool that ran writes a better one than this loop could, and recording
    # here as well would put every successful call in the record twice.
    entries_before = len(ledger)

    result = await _try_until_out_of_retries(tool, tool_call, call_id=call_id, budget=budget)

    if len(ledger) > entries_before:
        # The tool spoke for itself. Nothing to add.
        return result

    # It did not, so it never got as far as its own reporting — unreadable arguments, or
    # a tool that raised despite being contracted not to. This is the only record that
    # call will ever have (NFR-3). The error mark on the model library's reply is the one
    # signal we get that a tool failed rather than answered.
    succeeded = result.status != "error"
    ledger.record(
        kind=StepKind.TOOL_CALL,
        name=name,
        asked=asked,
        observed=result.text,
        succeeded=succeeded,
    )
    await events.emit(
        EventKind.TOOL_CALLED,
        f"Used the {_readable(name)} tool."
        if succeeded
        else f"The {_readable(name)} tool could not answer.",
        tool=name,
        outcome="answered" if succeeded else "failed",
    )
    return result


async def _try_until_out_of_retries(
    tool: BaseTool,
    tool_call: ToolCall,
    *,
    call_id: str,
    budget: RunBudget,
) -> ToolMessage:
    """Use one tool, trying again while this call still has retries left (FR-1.3)."""
    while True:
        try:
            # Invoked with the model's own call, not just its arguments, so the reply
            # comes back as a message already tied to the call it answers.
            return cast("ToolMessage", await tool.ainvoke({**tool_call, "id": call_id}))
        except Exception as exc:
            # Everything is caught here, deliberately. A tool reaches ShipBob,
            # downloads images and does arithmetic, and none of what can come out of
            # that is a reason for a claim to reach a representative as a server error
            # rather than as a clarification request (NFR-4). What is caught is written
            # down and handed to the model in plain words, never swallowed.
            if budget.has_retry_left(call_id):
                budget.spend_retry(call_id)
                logger.warning(
                    "tool_call_failed_trying_again",
                    tool=tool.name,
                    failure=type(exc).__name__,
                )
                continue

            logger.warning(
                "tool_call_failed",
                tool=tool.name,
                failure=type(exc).__name__,
            )
            return ToolMessage(
                # The exception's own words are kept out of this. They are written
                # for whoever wrote the tool, and a sentence like that in front of
                # the model is an invitation to reason about our internals.
                content=(
                    f"The {_readable(tool.name)} tool could not answer. "
                    "Carry on without it, or say what you cannot establish because of it."
                ),
                tool_call_id=call_id,
                name=tool.name,
                status="error",
            )


async def _pass_on_what_the_model_said(reply: AIMessage, *, events: EventStream) -> None:
    """Show a representative the model's own account of what it is doing."""
    said = reply.text.strip()
    if said:
        await events.emit(EventKind.THINKING, said)


def _refuse_a_used_budget(budget: RunBudget) -> None:
    """Stop a second pass from being run on a budget the first one already spent."""
    if budget.snapshot().steps_used:
        raise RuntimeError(
            "This run budget has already been spent by another pass. Budgets are per run: "
            "build a fresh RunBudget for every pass."
        )


def _model_turn_failed(
    reason: str,
    *,
    failure: str,
    concludes_with: type[BaseModel],
    budget: RunBudget,
    ledger: RunLedger,
) -> LoopOutcome[Answer]:
    """Write down a turn the model could not answer, and end the pass on it."""
    ledger.record(
        kind=StepKind.REASONING,
        name=concludes_with.__name__,
        asked="Ask the model what to do next.",
        observed=reason,
        succeeded=False,
    )
    logger.warning(
        "agent_turn_failed",
        form=concludes_with.__name__,
        failure=failure,
    )
    return _gave_up(reason, budget=budget, ledger=ledger)


def _gave_up(reason: str, *, budget: RunBudget, ledger: RunLedger) -> LoopOutcome[Answer]:
    """End a pass with no conclusion, carrying everything it established (FR-1.16)."""
    outcome: LoopOutcome[Answer] = LoopOutcome(
        answer=None,
        reason=reason,
        budget=budget.snapshot(),
        ledger=ledger.entries(),
    )
    return outcome


def _what_was_asked_for(name: str, args: dict[str, object]) -> str:
    """One plain sentence saying what a tool was asked to do, for the record."""
    if not args:
        return f"Use the {_readable(name)} tool."
    given = ", ".join(f"{key}: {value}" for key, value in args.items())
    return f"Use the {_readable(name)} tool with {given}."


def _readable(name: str) -> str:
    """Turn a tool's code name into something a person reads — `list_attachments`."""
    return name.replace("_", " ")
