from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final, Generic, TypedDict, TypeVar, cast

from langchain_core.exceptions import ModelError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from claim_agent.agent.budget import BudgetSnapshot, RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.ledger import LedgerEntry, RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.threads import PassThread
from claim_agent.agent.tools import ToolOutcome
from claim_agent.errors import ModelAnswerDidNotFitError, UpstreamError
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

# How many times a pass may ask the model to correct a conclusion that did not fit its
# form. One, because the second try is a changed question — it names what was wrong —
# and a third identical one is back to asking the same thing twice. Each costs a step.
_REPAIRS_ALLOWED: Final = 1


def _graph_limit(budget: RunBudget) -> int:
    """Work out the graph's own limit, always looser than the step allowance."""
    return budget.snapshot().steps_allowed * _MOVES_PER_STEP + _MOVES_TO_SPARE


class _PassState(TypedDict):
    """What one pass carries between moves, and what a thread keeps between passes.

    `messages` is appended to rather than replaced: a node hands back only what it
    added, and the graph keeps the whole conversation. That is what lets a later pass
    on the same thread continue from where this one stopped (FR-R.2).
    """

    messages: Annotated[list[BaseMessage], add_messages]
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
    thread: PassThread | None = None,
) -> LoopOutcome[Answer]:
    """Run one AI pass: ask, use tools, ask again, then conclude (FR-1.1, FR-1.3).

    Args:
        opening_messages: What the model is shown first. On a fresh thread that is the
            whole question; on a thread that already holds a conversation it is only the
            new turn, and the graph puts the earlier conversation in front of it.
        thread: Where this pass's conversation is kept, or `None` to keep none. A pass
            given a thread another pass already used continues that conversation, which
            is how a representative's note is answered by the investigation that
            produced the report rather than by a retelling of it (FR-R.2).
    """
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

        budget.record_usage(getattr(reply, "usage_metadata", None))
        await _pass_on_what_the_model_said(reply, events=events)
        return {"messages": [reply]}

    async def act(state: _PassState) -> dict[str, object]:
        """Carry out whatever the model just asked for, and hand back what came of it.

        The calls of one turn run at the same time: they are independent of one another,
        and the per-claim memo already makes two callers asking the same question do the
        work once. Their answers go back in the order they were asked for, because the
        model reads them against its own list.

        A turn that asks for more tools than a turn may use gets the first ones carried
        out and the rest declined in words, each under its own call id — the provider
        requires an answer to every call, and a declined call answered plainly is one the
        model can ask for again next turn (FR-1.3).
        """
        asked_for = cast(AIMessage, state["messages"][-1])
        allowed = budget.tool_calls_allowed_per_step
        carried_out, declined = asked_for.tool_calls[:allowed], asked_for.tool_calls[allowed:]
        if declined:
            logger.warning(
                "agent_turn_asked_for_too_many_tools",
                asked_for=len(asked_for.tool_calls),
                allowed=allowed,
            )

        answers = await asyncio.gather(
            *(
                _carry_out(
                    tool_call,
                    tools_by_name=tools_by_name,
                    ledger=ledger,
                    events=events,
                )
                for tool_call in carried_out
            )
        )
        held_back = [
            _declined(tool_call, asked=len(asked_for.tool_calls), allowed=allowed, ledger=ledger)
            for tool_call in declined
        ]
        return {"messages": [*answers, *held_back]}

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

    # With a thread, the graph writes every move to it and reads whatever an earlier
    # pass left there first, so the opening messages land after that conversation.
    # The outcome is reset because it belongs to the pass that produced it.
    graph = builder.compile(checkpointer=thread.checkpointer if thread is not None else None)
    config = RunnableConfig(recursion_limit=_graph_limit(budget))
    if thread is not None:
        config["configurable"] = {"thread_id": thread.thread_id}

    finished = await graph.ainvoke(
        {"messages": list(opening_messages), "outcome": None},
        config=config,
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
    """Ask the model to fill in the form this pass ends on (NFR-2).

    An answer that does not fit the form is not the end of the pass. The validator's own
    account of what was wrong is put in front of the model and the form is asked for
    once more — a changed question, not the same one twice. Only when that also fails,
    or there is no step left to spend on it, does the pass give up, and even then it
    carries everything it established (FR-1.16, NFR-4).
    """
    request = closing_request
    asked = f"Draw a conclusion for this pass, in the shape of {concludes_with.__name__}."
    repairs_left = _REPAIRS_ALLOWED

    while True:
        try:
            answer = await structured.ask(
                concludes_with,
                [*messages, HumanMessage(content=request)],
                on_usage=budget.record_usage,
            )
        except ModelAnswerDidNotFitError as did_not_fit:
            ledger.record(
                kind=StepKind.REASONING,
                name=concludes_with.__name__,
                asked=asked,
                observed=_what_did_not_fit(did_not_fit),
                succeeded=False,
            )
            if repairs_left == 0:
                logger.warning("agent_conclusion_unusable", form=concludes_with.__name__)
                return _gave_up(
                    f"{did_not_fit.message} It was asked once to correct it, and the "
                    "corrected answer did not fit either.",
                    budget=budget,
                    ledger=ledger,
                )
            if not budget.has_step_left():
                logger.warning("agent_conclusion_unusable", form=concludes_with.__name__)
                return _gave_up(
                    f"{did_not_fit.message} The run had no step left to ask for a corrected one.",
                    budget=budget,
                    ledger=ledger,
                )
            repairs_left -= 1
            budget.spend_step()
            logger.info("agent_conclusion_repair_asked", form=concludes_with.__name__)
            request = _repair_request(closing_request, did_not_fit)
            asked = f"Ask again for {concludes_with.__name__}, naming what did not fit last time."
            continue
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
        break

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


def _repair_request(closing_request: str, did_not_fit: ModelAnswerDidNotFitError) -> str:
    """The closing question again, with what was wrong with the last answer under it."""
    problems = "\n".join(f"- {problem}" for problem in did_not_fit.problems)
    return (
        f"{closing_request}\n\n"
        "Your previous answer did not fit the form, for these reasons:\n"
        f"{problems}\n"
        "Fill the form in again, correcting exactly those fields and keeping everything "
        "else as you had it."
    )


def _what_did_not_fit(did_not_fit: ModelAnswerDidNotFitError) -> str:
    """One line for the record saying how the answer missed the form."""
    return f"{did_not_fit.message} {' '.join(did_not_fit.problems)}"


async def _carry_out(
    tool_call: ToolCall,
    *,
    tools_by_name: dict[str, BaseTool],
    ledger: RunLedger,
    events: EventStream,
) -> ToolMessage:
    """Do the one thing the model asked for, and put the result into words for it."""
    # The provider requires every call to be answered under its own id; one made up
    # from where the call appeared is the fallback for a call that arrived without one.
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

    result = await _carry_out_once(tool, tool_call, call_id=call_id)

    if isinstance(getattr(result, "artifact", None), ToolOutcome):
        # The tool spoke for itself: every investigation tool hands its outcome back as
        # the message's artifact, and writes its own record on the way. Recording here
        # as well would put every successful call in the record twice. Judged by the
        # reply itself rather than by counting ledger entries, because several calls
        # run at once and another call's entry could land in between.
        return result

    # It did not: unreadable arguments, a tool that raised, or a tool that keeps no
    # record of its own. This is the only record that call will ever have (NFR-3).
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


def _declined(tool_call: ToolCall, *, asked: int, allowed: int, ledger: RunLedger) -> ToolMessage:
    """Answer a call that was over the turn's allowance, and write it down (FR-1.3)."""
    name = tool_call["name"]
    refusal = (
        f"This turn asked for {asked} tools and a turn may use at most {allowed}, so this "
        "call was not carried out. Ask for it again on your next turn if you still need it."
    )
    ledger.record(
        kind=StepKind.TOOL_CALL,
        name=name,
        asked=_what_was_asked_for(name, tool_call["args"]),
        observed=refusal,
        succeeded=False,
    )
    return ToolMessage(
        content=refusal,
        tool_call_id=tool_call["id"] or f"unnamed-call-{len(ledger)}",
        name=name,
        status="error",
    )


async def _carry_out_once(tool: BaseTool, tool_call: ToolCall, *, call_id: str) -> ToolMessage:
    """Use one tool once, and put any failure into words the model can act on (NFR-4).

    Not retried. Every expected failure — ShipBob unreachable, an image that will not
    download, arguments that do not parse — is already caught inside the tool and answered
    in words, so an exception reaching here is a bug in the tool, and a bug does not mend
    itself on a second try.
    """
    try:
        # Invoked with the model's own call, not just its arguments, so the reply comes
        # back as a message already tied to the call it answers.
        return cast("ToolMessage", await tool.ainvoke({**tool_call, "id": call_id}))
    except Exception as exc:
        # Caught deliberately: nothing a tool does is a reason for a claim to reach a
        # representative as a server error rather than as a clarification request.
        logger.warning("tool_call_failed", tool=tool.name, failure=type(exc).__name__)
        return ToolMessage(
            # The exception's own words are kept out: they are written for whoever wrote
            # the tool, and would invite the model to reason about our internals.
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
