"""The tool-use loop every AI pass in this system runs inside (FR-1.1, FR-1.3).

This is the file that makes the system an agent rather than a function. Nothing
in here decides which tool to use, in what order, or how many times. The model is
shown the tools it has and asked what it wants to do next; whatever it asks for is
carried out; the result is put back in front of it; it is asked again. A claim
with no photographs costs a couple of turns and a claim with six costs more,
because the work follows the evidence rather than a script somebody wrote in
advance (FR-1.1).

The same loop runs twice over. Once to work out which products a claim is for, and
once for each of those products. The three things that differ — what the pass is
asked, which tools it holds, and which form it ends on — are arguments, so there
is one loop rather than two near-identical copies drifting apart.

**One pass, in four stages.**

* **Prepare** — the opening question, with the pass's tools attached to the model.
* **Agent, then act** — ask the model; carry out whatever it asked for; put the
  results into the conversation; ask again. One turn of that costs one step.
* **Conclude** — a separate question, asking the model to fill in the form this
  pass ends on.
* **Give up** — the steps ran out, or the model failed. The pass stops and hands
  back everything it had established by then, and the caller turns that into an
  escalation to a support representative (FR-1.16, NFR-4).

**Concluding is a separate question, not a fifth tool.** The obvious alternative
is a "submit your answer" tool the model calls when it is finished. We do not do
that, for two reasons. The agent's tools are enumerated by FR-1.2 and there are
four of them; adding a fifth would make the list in the requirements and the list
in the code disagree, and that list is the structural guarantee that the agent
cannot send an email or move money. And a tool call is something the model may or
may not make, while a question asked through the structured asker either comes
back as a filled-in form or raises — which is exactly the guarantee NFR-2 asks
for. A model that simply stops calling tools still gets asked for its conclusion.

**It always terminates, and the promise is kept outside the conversation**
(FR-1.3). Every turn of the loop spends one step, the allowance is a fixed
positive number that nothing can raise, and there is no other way out of the
loop, so the loop runs at most that many times whatever the model does. The
allowance lives in the run's own budget object and is never written into the
prompt: a limit the model can read is a limit the model can argue with. Retrying
a failed tool call is bounded the same way, per individual call.

**Nothing here raises for an ordinary failure.** A model that cannot be reached,
an answer that will not fit the form, a tool that breaks, a budget that runs out:
each one ends as a `LoopOutcome` with no answer and a plain sentence saying why.
That is what lets the caller escalate every one of them to a person instead of
turning some into an error page (NFR-4).

**How the pass is put together.** Three moves and the choices between them, built
as a state graph:

    start → think ⇄ act
              ↓
           conclude → end

*Think* asks the model what it wants to do next. *Act* runs whatever it asked for.
Whether the run goes round again, stops to conclude, or gives up is decided by
what the model just said — which is the point. A pass that asks for no tools at
all concludes on its very first move, and a pass that keeps finding things worth
looking at goes round until its allowance runs out.

**Two limits bound this run, and only one of them may ever be the one that stops
it.** A state graph carries its own limit on how many moves it will make, and it
enforces that limit by raising. A run that ends by raising loses everything it
established, and FR-1.16 says the opposite has to happen: what was found is
carried forward to a person. So the graph's limit is deliberately set well above
the step allowance, and the step allowance is what actually trips. If those two
were ever the other way round, a long investigation would reach a rep as an error
page instead of as a claim with findings attached. `_graph_limit` is where that is
kept true.
"""

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

# How much room the graph is given before it stops a run itself, worked out from the
# step allowance rather than written down as a number. Every step the model takes is
# two moves through the graph — it thinks, then its tools run — plus a few for
# starting and concluding.
#
# It exists only as a backstop and must never be what actually stops a run. The graph
# ends a run that reaches its limit by raising, and a run that ends by raising loses
# everything it established; FR-1.16 says the opposite has to happen, which is that
# the findings are carried forward to a person. So our own step allowance is always
# the tighter of the two, and it is the one that trips.
_MOVES_PER_STEP = 2
_MOVES_TO_SPARE = 10


def _graph_limit(budget: RunBudget) -> int:
    """Work out the graph's own limit, always looser than the step allowance.

    Kept deliberately generous. If this were ever the tighter bound, a long
    investigation would end in an exception instead of an escalation, and a rep
    would get an error where they should have got a claim with findings attached.
    """
    return budget.snapshot().steps_allowed * _MOVES_PER_STEP + _MOVES_TO_SPARE


class _PassState(TypedDict):
    """What one pass carries between moves.

    `messages` is the conversation so far — the opening question, what the model
    said, and what its tools answered. `outcome` stays `None` until the pass has
    either concluded or given up, and setting it is what ends the run.
    """

    messages: list[BaseMessage]
    outcome: LoopOutcome[Any] | None


@dataclass(frozen=True)
class LoopOutcome(Generic[Answer]):
    """Everything one pass established, whether or not it reached a conclusion.

    This is the only thing a pass hands back, and it is deliberately the same
    shape whether the pass succeeded or not. A pass that gave up is an ordinary
    result to be read, not an exception to be caught: the caller looks at
    `answer`, finds nothing there, and escalates the claim to a representative
    with the reason and the record attached (FR-1.16, NFR-4).

    Frozen, because it is the account of something that has already happened.

    Fields:
        answer: The filled-in form this pass ends on, or `None` when it gave up
            before reaching one. `None` is the normal, expected shape of a
            failure here — no exception is raised for it.
        reason: Why it gave up, in one plain sentence a representative can read.
            `None` exactly when there is an answer.
        budget: What the pass spent, and which of its limits it reached. Goes
            into the report so a representative can see why a run stopped without
            reading logs (NFR-3).
        ledger: Every step in the record this pass was handed, in order — the
            tools it used, what came back, and anything that failed. Anything the
            caller had already written on that record is in here too, so a report
            can be built from this alone. This is what "carrying forward whatever
            was established" means for a pass that gave up before concluding
            (FR-1.16): the work is still here, only the conclusion is missing.
    """

    answer: Answer | None
    reason: str | None
    budget: BudgetSnapshot
    ledger: tuple[LedgerEntry, ...]

    @property
    def gave_up(self) -> bool:
        """Whether the pass stopped without reaching a conclusion.

        Worked out from `answer` rather than stored beside it, so the two can
        never contradict each other. A stored flag would eventually be set wrong
        in one branch, and a caller trusting it would escalate a claim that had
        an answer, or approve one that did not.
        """
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
    claim_line_id: str | None = None,
) -> LoopOutcome[Answer]:
    """Run one AI pass: ask, use tools, ask again, then conclude (FR-1.1, FR-1.3).

    Terminates in every case. It returns when the model stops asking for tools and
    a conclusion has been drawn, or when the pass gives up — and it gives up rather
    than raising for every failure that can happen to a claim (NFR-4).

    Args:
        opening_messages: The question this pass starts from, already assembled by
            `claim_agent.agent.prompts`, shared rules included. Copied rather than
            added to, so the caller's list is not changed underneath it.
        tools: The tools this pass may use, bound to the model before the first
            question. The model chooses which of them to call and when; nothing
            here sequences them (FR-1.1). Every tool the agent has is a read or a
            reasoning tool, and there is no way to send an email or move money
            from in here, because no such tool exists in the package (FR-1.2).
        concludes_with: The form this pass ends on — `ClaimSplit` for the triage
            pass, `InvestigationConclusion` for one product's run.
        closing_request: What to say when asking for that form, in the caller's
            own words. The wording of a question belongs with the other prompts
            and not in here.
        chat: The model to ask. The tools are bound to this.
        structured: The same model, wrapped so that the conclusion either fits the
            form or fails (NFR-2). Pass the wrapper built around the very model in
            `chat`, so the conclusion is drawn by whatever did the investigating.
        budget: This run's step, retry and image allowance. **Build a fresh one per
            pass** — a claim with four products has four budgets, not one shared
            between them (FR-1.3). Handing over a budget that has already spent a
            step is refused outright; see the note on the failure below.
        ledger: Where each step is written down as it happens (NFR-3, NFR-5). The
            entries come back in the outcome, so a caller can put them straight
            into its report.
        events: Where the run narrates itself while it works. Every tool call and
            every remark the model makes along the way goes here. A stream built
            with no sink keeps the events and sends them nowhere, which is what a
            caller that only wants the finished answer should use.
        claim_line_id: The damaged product this pass answers for, named on every
            event so a screen watching several products at once can tell them
            apart. `None` for a pass about the whole claim.

    Returns:
        The filled-in form with the record of how it was reached, or no answer and
        a plain sentence saying why not. Both are ordinary outcomes.

    Raises:
        RuntimeError: the budget handed in had already spent a step, which means
            two passes are sharing one. That is a mistake in our own code rather
            than something that happened to the claim, so it is raised loudly
            instead of quietly halving a second pass's allowance — exactly as
            `RunBudget` treats a step spent past its limit.
    """
    _refuse_a_used_budget(budget)

    model = chat.bind_tools(list(tools))
    tools_by_name = {tool.name: tool for tool in tools}

    async def think(state: _PassState) -> dict[str, object]:
        """Ask the model what it wants to do next.

        This is the move that makes the whole thing an agent: the model is handed
        the tools and decides for itself which to call, in what order, how many
        times, and when it has seen enough (FR-1.1). Nothing here sequences them.

        Spending a step is the first thing that happens, and the allowance is
        checked before that. Between them they are the whole termination
        guarantee: there is no way back into this node that does not pay for it
        (FR-1.3).
        """
        if not budget.has_step_left():
            snapshot = budget.snapshot()
            logger.info(
                "agent_pass_out_of_steps",
                claim_line_id=claim_line_id,
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
                    claim_line_id=claim_line_id,
                )
            }
        except ModelError as exc:
            # The model library marks each provider condition it knows about as
            # worth another try or not. Both end the pass here — a turn is not
            # retried, because the step budget is the only allowance a turn has —
            # but they send a reader looking in different places, so they are
            # reported differently.
            return {
                "outcome": _model_turn_failed(
                    "The model provider could not be reached."
                    if exc.is_retryable
                    else "The model provider refused the request.",
                    failure=type(exc).__name__,
                    concludes_with=concludes_with,
                    budget=budget,
                    ledger=ledger,
                    claim_line_id=claim_line_id,
                )
            }

        await _pass_on_what_the_model_said(reply, events=events, claim_line_id=claim_line_id)
        return {"messages": [*state["messages"], reply]}

    async def act(state: _PassState) -> dict[str, object]:
        """Carry out whatever the model just asked for, and hand back what came of it.

        A tool never raises into this: a failure comes back as something the model
        can read and reason about, so a run can recover from one bad image rather
        than losing the claim over it (NFR-4).
        """
        asked_for = state["messages"][-1]
        answers: list[BaseMessage] = [
            await _carry_out(
                tool_call,
                tools_by_name=tools_by_name,
                budget=budget,
                ledger=ledger,
                events=events,
                claim_line_id=claim_line_id,
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
                claim_line_id=claim_line_id,
            )
        }

    def what_next(state: _PassState) -> str:
        """Decide where the pass goes after the model has spoken.

        Three ways onward, and the middle one is the model's own choice rather than
        ours: it asked for tools, so they run. Asking for none is how it says it has
        seen enough, which is the cheap case FR-1.1 describes — a claim with nothing
        to look at reaches a conclusion on the very first move.
        """
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
    claim_line_id: str | None,
) -> LoopOutcome[Answer]:
    """Ask the model to fill in the form this pass ends on (NFR-2).

    Asked as its own question, with the whole conversation behind it, so the
    conclusion is drawn from everything the pass saw. It costs no extra step: the
    turn in which the model stopped asking for tools is the turn that pays for it.

    A conclusion that will not fit the form is not asked for again. Asking the
    identical question in the identical way is the least likely thing to produce a
    different shape, and the reasoning is set out in full in
    `claim_agent.agent.llm`. The pass gives up instead, and the claim goes to a
    person carrying everything the run established (NFR-4).
    """
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
            claim_line_id=claim_line_id,
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
    claim_line_id: str | None,
) -> ToolMessage:
    """Do the one thing the model asked for, and put the result into words for it.

    Whatever comes back — an answer, a refusal, a tool that broke — comes back as
    a message the model can read and reason about on its next turn. Nothing here
    ends the pass: the model is told what happened and decides what to do about
    it, which is the whole point of a tool-use loop (FR-1.1).

    Retrying is bounded per individual call, so one flaky read early on cannot eat
    the allowance of a later one (FR-1.3).
    """
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
            claim_line_id=claim_line_id,
            tool=name,
            outcome="unknown_tool",
        )
        return ToolMessage(content=refusal, tool_call_id=call_id, name=name, status="error")

    # Noted before the call so that afterwards we can tell whether the tool wrote its
    # own record. A tool that ran writes a better one than this loop could: it knows
    # what it found and which image or shipment it found it in, and it can name that
    # in the entry. Recording here as well would put every successful call in the
    # record twice and narrate it twice on screen.
    entries_before = len(ledger)

    result = await _try_until_out_of_retries(
        tool, tool_call, call_id=call_id, budget=budget, claim_line_id=claim_line_id
    )

    if len(ledger) > entries_before:
        # The tool spoke for itself. Nothing to add.
        return result

    # It did not, which means it never got as far as its own reporting — arguments it
    # could not read, or a tool that raised in spite of being contracted not to. This
    # is then the only record that call will ever have, so it is made here rather than
    # left out (NFR-3).
    #
    # A tool that fails is contracted to say so in its answer rather than raise, so a
    # plain answer is recorded as a step that completed. The one signal a tool can give
    # us that it did not is the error mark the model library puts on its own reply.
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
        claim_line_id=claim_line_id,
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
    claim_line_id: str | None,
) -> ToolMessage:
    """Use one tool, trying again while this call still has retries left (FR-1.3).

    A tool is contracted never to raise: a failure it knows about comes back as
    words the model can reason about. This is what happens when one breaks that
    contract anyway — a bug, or something nobody anticipated in the four separate
    things the tools touch. It is turned into words too, so that a broken tool
    escalates a claim to a person instead of turning the whole request into an
    error (NFR-4, NFR-6).
    """
    while True:
        try:
            # Invoked with the model's own call rather than just its arguments, so
            # the reply comes back as a message already tied to the call it
            # answers. That is the model library's contract for a tool call, and
            # it is why the result can be relied on to be a message.
            return cast("ToolMessage", await tool.ainvoke({**tool_call, "id": call_id}))
        except Exception as exc:
            # Everything is caught here, deliberately, and this is one of the two
            # places in the system where that is right. A tool reaches ShipBob,
            # downloads images and does arithmetic; anything at all can come out
            # of that, and none of it is a reason for a claim to reach a
            # representative as a server error rather than as an escalation she
            # can act on (NFR-4). What is caught is written down and handed to the
            # model in plain words, never swallowed.
            if budget.has_retry_left(call_id):
                budget.spend_retry(call_id)
                logger.warning(
                    "tool_call_failed_trying_again",
                    claim_line_id=claim_line_id,
                    tool=tool.name,
                    failure=type(exc).__name__,
                )
                continue

            logger.warning(
                "tool_call_failed",
                claim_line_id=claim_line_id,
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


async def _pass_on_what_the_model_said(
    reply: AIMessage, *, events: EventStream, claim_line_id: str | None
) -> None:
    """Show a representative the model's own account of what it is doing.

    A pass takes a while and says nothing while it works, so the sentence the
    model writes alongside its tool calls — "the second photograph is too dark to
    read, so I will look at the third" — is the most useful thing anyone watching
    can be shown. A turn with no words to it emits nothing rather than an empty
    message.

    The remark is passed on whole, line breaks and all. It used to be cut at the
    length of a ledger entry, which lost the end of the longer ones — and the end
    is the part saying what the run decided to do next. There is no unbounded
    amount of text to defend against here: how much the model may write in one
    reply is already settled by the model itself. The ledger keeps its own short
    entries, because a record kept for review is a different thing from a run
    talking while it works.
    """
    said = reply.text.strip()
    if said:
        await events.emit(EventKind.THINKING, said, claim_line_id=claim_line_id)


def _refuse_a_used_budget(budget: RunBudget) -> None:
    """Stop a second pass from being run on a budget the first one already spent.

    Budgets are per run, so a claim with four products has four of them (FR-1.3).
    A shared one would give the last product a fraction of the allowance the first
    got, and the only sign of it would be claims escalating for no visible reason.
    Only the step count is checked, because steps are spent in this file and
    nowhere else: an image allowance may legitimately have been drawn on before the
    pass started.

    Raises:
        RuntimeError: this budget has already been used by a pass.
    """
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
    claim_line_id: str | None,
) -> LoopOutcome[Answer]:
    """Write down a turn the model could not answer, and end the pass on it.

    Recorded in the ledger as well as returned, because "why was this escalated?"
    has to be answerable from the record a representative is handed, and a pass
    that failed on its first turn would otherwise leave a record with nothing
    wrong in it (NFR-3).
    """
    ledger.record(
        kind=StepKind.REASONING,
        name=concludes_with.__name__,
        asked="Ask the model what to do next.",
        observed=reason,
        succeeded=False,
    )
    logger.warning(
        "agent_turn_failed",
        claim_line_id=claim_line_id,
        form=concludes_with.__name__,
        failure=failure,
    )
    return _gave_up(reason, budget=budget, ledger=ledger)


def _gave_up(reason: str, *, budget: RunBudget, ledger: RunLedger) -> LoopOutcome[Answer]:
    """End a pass with no conclusion, carrying everything it established (FR-1.16).

    Every way a pass can fail comes through here, so that a caller only ever has
    one shape to read and every failure reaches a representative with the run's
    record attached rather than as an exception (NFR-4).
    """
    outcome: LoopOutcome[Answer] = LoopOutcome(
        answer=None,
        reason=reason,
        budget=budget.snapshot(),
        ledger=ledger.entries(),
    )
    return outcome


def _what_was_asked_for(name: str, args: dict[str, object]) -> str:
    """One plain sentence saying what a tool was asked to do, for the record.

    The arguments are named and shown because they are what makes a step
    reviewable — which attachment was looked at, which shipment was priced. They
    are identifiers by design, and the ledger cuts anything over-long, so a
    surprisingly large argument makes for a truncated sentence rather than a
    record nobody can read.
    """
    if not args:
        return f"Use the {_readable(name)} tool."
    given = ", ".join(f"{key}: {value}" for key, value in args.items())
    return f"Use the {_readable(name)} tool with {given}."


def _readable(name: str) -> str:
    """Turn a tool's code name into something a person reads — `list_attachments`."""
    return name.replace("_", " ")
