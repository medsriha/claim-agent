from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.exceptions import ModelAuthenticationError, ModelConnectionError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from tests.fakes.model import ScriptedModel, scripted

from claim_agent.agent.budget import BudgetLimit, RunBudget
from claim_agent.agent.events import EventKind, EventStream, RunEvent
from claim_agent.agent.ledger import RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.loop import LoopOutcome, run_agent_pass
from claim_agent.agent.schemas import ClaimSplit, InvestigationConclusion
from claim_agent.agent.threads import PassThreads
from claim_agent.domain.outcome import Recommendation
from claim_agent.policy import Policy

CLOSING_REQUEST = "Say which products this claim is for."


# --- Building the pieces a pass needs ---------------------------------------


def budget_of(*, steps: int = 6) -> RunBudget:
    """A fresh budget with small limits, so a test can use one up quickly."""
    return RunBudget(Policy(max_agent_steps=steps))


def a_split(reasoning: str = "The claim is for one bottle.") -> ClaimSplit:
    """A filled-in triage form, standing in for whatever the model would really say."""
    return ClaimSplit(reasoning=reasoning)


def a_conclusion() -> InvestigationConclusion:
    """A filled-in investigation form, for the pass that ends on the other shape."""
    return InvestigationConclusion(
        evidence=(),
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
        reasoning="Nothing was established.",
        email_subject="About your claim",
        email_body="We are looking into it.",
    )


def asks_for(name: str, call_id: str = "call-1", **args: Any) -> AIMessage:
    """A model reply that asks for one tool, the way a real one arrives."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


@tool
async def list_attachments(case_id: str) -> str:
    """List the images attached to a case."""
    return f"two images on {case_id}"


@tool
async def inspect_image(attachment_id: str) -> str:
    """Say what one image shows."""
    return f"{attachment_id} shows a cracked bottle"


def a_tool_that_fails(times: int) -> BaseTool:
    """A tool that raises on its first `times` uses and then answers.

    Tools are contracted never to raise. This one does, so the loop's answer to a broken
    contract can be checked.
    """
    used = {"count": 0}

    @tool
    async def read_case(case_id: str) -> str:
        """Read a case."""
        used["count"] += 1
        if used["count"] <= times:
            raise RuntimeError("the read failed")
        return f"{case_id} read on attempt {used['count']}"

    return read_case


async def run_triage(
    model: ScriptedModel,
    *,
    tools: Sequence[BaseTool] = (),
    budget: RunBudget | None = None,
    ledger: RunLedger | None = None,
    events: EventStream | None = None,
) -> LoopOutcome[ClaimSplit]:
    """Run one pass that ends on the triage form, with everything else defaulted.

    The structured asker is given a single attempt so that one queued reply answers
    exactly one question. Its own retrying is tested where it lives; here it would only
    make the scripts harder to read.
    """
    return await run_agent_pass(
        opening_messages=[SystemMessage(content="The rules."), HumanMessage(content="Which?")],
        tools=tools,
        concludes_with=ClaimSplit,
        closing_request=CLOSING_REQUEST,
        chat=model,
        structured=StructuredModel(model, max_attempts=1),
        budget=budget or budget_of(),
        ledger=ledger or RunLedger(),
        events=events or EventStream(),
    )


def two_tools_that_notice_each_other() -> tuple[BaseTool, BaseTool, dict[str, bool]]:
    """Two tools where each can only finish once the other has started.

    Run one after the other, the first would wait for ever for a second that never
    began. Run together, both finish. That is the whole test of concurrency, with no
    timing in it.
    """
    started = {"left": asyncio.Event(), "right": asyncio.Event()}
    seen = {"overlapped": False}

    @tool
    async def read_left(case_id: str) -> str:
        """Read the left-hand record."""
        started["left"].set()
        await asyncio.wait_for(started["right"].wait(), timeout=1.0)
        seen["overlapped"] = True
        return f"left of {case_id}"

    @tool
    async def read_right(case_id: str) -> str:
        """Read the right-hand record."""
        started["right"].set()
        await asyncio.wait_for(started["left"].wait(), timeout=1.0)
        return f"right of {case_id}"

    return read_left, read_right, seen


def asks_for_several(*names: str) -> AIMessage:
    """A model reply that asks for several tools in one turn, each under its own id."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {"case_id": "CASE-1"}, "id": f"call-{n}", "type": "tool_call"}
            for n, name in enumerate(names, start=1)
        ],
    )


def tool_names_in(outcome: LoopOutcome[Any]) -> list[str]:
    """The tools a pass used, in the order it used them."""
    return [entry.name for entry in outcome.ledger if entry.kind is StepKind.TOOL_CALL]


def events_of(stream: EventStream, kind: EventKind) -> list[RunEvent]:
    """Everything of one kind the run said about itself, in order."""
    return [event for event in stream.events() if event.kind is kind]


# --- The model decides what to look at, and how much to look at (FR-1.1) ----


async def test_a_pass_with_nothing_to_look_at_concludes_on_its_first_turn() -> None:
    """FR-1.1: a claim with nothing to investigate costs one turn, not a fixed sequence.

    This is the cheap case the requirement is really about. The tools are there and the
    model is free to use them; it decides it does not need to, and the pass is over.
    """
    model = scripted(AIMessage(content="Nothing here needs looking at."), a_split())
    budget = budget_of(steps=6)

    outcome = await run_triage(model, tools=[list_attachments, inspect_image], budget=budget)

    assert outcome.answer == a_split()
    assert outcome.gave_up is False
    assert outcome.reason is None
    assert tool_names_in(outcome) == []
    assert outcome.budget.steps_used == 1


async def test_the_tools_are_put_in_front_of_the_model_for_it_to_choose_among() -> None:
    """FR-1.1: nothing sequences the tools — every one of them is offered every turn."""
    model = scripted(asks_for("inspect_image", attachment_id="ATT-01"), "done", a_split())

    await run_triage(model, tools=[list_attachments, inspect_image])

    assert model.bound_tools == ["list_attachments", "inspect_image"]
    assert model.asked[0].tool_names == ("list_attachments", "inspect_image")
    # The one it chose is the only one that ran. Nothing made it call the other first.
    assert model.asked[1].text.endswith("ATT-01 shows a cracked bottle")


async def test_a_pass_uses_two_tools_and_then_concludes() -> None:
    """FR-1.1: a claim with things to look at takes as many turns as it asks for."""
    model = scripted(
        asks_for("list_attachments", call_id="call-1", case_id="CASE-1003"),
        asks_for("inspect_image", call_id="call-2", attachment_id="ATT-01"),
        AIMessage(content="That is enough to answer."),
        a_split(),
    )
    budget = budget_of(steps=6)

    outcome = await run_triage(model, tools=[list_attachments, inspect_image], budget=budget)

    assert tool_names_in(outcome) == ["list_attachments", "inspect_image"]
    assert outcome.answer == a_split()
    # Three turns of the loop: two that asked for a tool, one that stopped asking. The
    # conclusion itself costs no extra step.
    assert outcome.budget.steps_used == 3


async def test_what_a_tool_answered_is_put_back_in_front_of_the_model() -> None:
    """FR-1.1: the model reasons on what it found, which is what makes this a loop."""
    model = scripted(
        asks_for("inspect_image", attachment_id="ATT-01"),
        AIMessage(content="A cracked bottle is enough."),
        a_split(),
    )

    await run_triage(model, tools=[inspect_image])

    second_question = model.asked[1].text
    assert "ATT-01 shows a cracked bottle" in second_question


async def test_the_pass_asks_for_its_conclusion_in_the_callers_own_words() -> None:
    """NFR-2: the conclusion is a separate question, asked for as a named form."""
    model = scripted("done", a_split())

    await run_triage(model)

    assert [ask.schema_name for ask in model.asked] == [None, "ClaimSplit"]
    assert CLOSING_REQUEST in model.asked[-1].text


# --- It always terminates (FR-1.3, FR-1.16) ---------------------------------


async def test_a_model_that_asks_for_tools_for_ever_stops_at_the_step_budget() -> None:
    """FR-1.3: the allowance is in the loop, not the prompt, so nothing can talk past it.

    The script here is far longer than the budget. What stops the run is the budget, and
    the leftover replies are the proof of it.
    """
    endless = [asks_for("list_attachments", case_id="CASE-1003") for _ in range(20)]
    model = scripted(*endless)
    budget = budget_of(steps=3)

    outcome = await run_triage(model, tools=[list_attachments], budget=budget)

    assert outcome.gave_up is True
    assert outcome.answer is None
    assert outcome.budget.steps_used == 3
    assert BudgetLimit.STEPS in outcome.budget.limits_reached
    assert len(model.replies) == 17, "the loop stopped, not the script"


async def test_a_pass_that_runs_out_of_steps_hands_back_what_it_established() -> None:
    """FR-1.16: exhaustion requests clarification with findings, never an empty result."""
    model = scripted(
        asks_for("inspect_image", attachment_id="ATT-01"),
        *[asks_for("list_attachments", case_id="CASE-1003") for _ in range(5)],
    )
    budget = budget_of(steps=2)

    outcome = await run_triage(model, tools=[list_attachments, inspect_image], budget=budget)

    assert outcome.answer is None
    assert outcome.reason is not None
    assert "steps" in outcome.reason
    # The work is still here. Only the conclusion is missing.
    assert tool_names_in(outcome) == ["inspect_image", "list_attachments"]
    assert outcome.ledger[0].observed == "ATT-01 shows a cracked bottle"


# --- Every failure ends in front of a person (NFR-4) ------------------------


async def test_a_conclusion_that_does_not_fit_the_form_is_asked_for_once_more() -> None:
    """NFR-2, NFR-4: a formatting slip costs one repair turn, not the whole investigation."""
    model = scripted("done", {"nothing": "that fits the form"}, a_split("Fixed on the second try."))
    budget = budget_of(steps=6)

    outcome = await run_triage(model, budget=budget)

    assert outcome.gave_up is False
    assert outcome.answer is not None
    assert outcome.answer.reasoning == "Fixed on the second try."
    asked_for_the_form = [ask for ask in model.asked if ask.schema_name == "ClaimSplit"]
    assert len(asked_for_the_form) == 2
    # The second question is a changed one: it names what was wrong the first time.
    repair = asked_for_the_form[1].text
    assert "did not fit the form" in repair
    assert "not in the shape of ClaimSplit" in repair
    assert CLOSING_REQUEST in repair
    # One failed record, then one that succeeded, and the repair cost a step.
    assert [entry.succeeded for entry in outcome.ledger] == [False, True]
    assert outcome.budget.steps_used == 2


async def test_a_corrected_answer_that_still_does_not_fit_ends_the_pass_rather_than_raising() -> (
    None
):
    """NFR-2: one repair is a changed question; a third identical ask would not be."""
    model = scripted("done", {"nothing": "that fits"}, {"still": "nothing that fits"})

    outcome = await run_triage(model)

    assert outcome.gave_up is True
    assert outcome.reason is not None
    assert outcome.reason.startswith(
        "The model's answer did not fit the form it was asked to fill in."
    )
    assert "corrected answer did not fit either" in outcome.reason
    asked_for_the_form = [ask for ask in model.asked if ask.schema_name == "ClaimSplit"]
    assert len(asked_for_the_form) == 2
    failed = [entry for entry in outcome.ledger if not entry.succeeded]
    assert [entry.name for entry in failed] == ["ClaimSplit", "ClaimSplit"]


async def test_a_repair_is_not_asked_for_when_no_step_is_left_to_pay_for_it() -> None:
    """FR-1.3: the repair turn is a step like any other, and cannot exceed the allowance."""
    model = scripted("done", {"nothing": "that fits the form"}, a_split("never reached"))

    outcome = await run_triage(model, budget=budget_of(steps=1))

    assert outcome.gave_up is True
    assert outcome.reason is not None
    assert "no step left to ask for a corrected one" in outcome.reason
    asked_for_the_form = [ask for ask in model.asked if ask.schema_name == "ClaimSplit"]
    assert len(asked_for_the_form) == 1


async def test_a_provider_that_fails_at_the_conclusion_ends_the_pass_rather_than_raising() -> None:
    """NFR-4: a model that cannot be reached returns a rep action, not a crash."""
    model = scripted("done", ModelConnectionError("the socket closed"))

    outcome = await run_triage(model)

    assert outcome.answer is None
    assert outcome.reason == "The model provider could not be reached."


async def test_a_model_that_fails_mid_pass_ends_the_pass_rather_than_raising() -> None:
    """NFR-4: a failure on an ordinary turn is a result to read, not an exception."""
    model = scripted(ModelConnectionError("the socket closed"))
    budget = budget_of(steps=4)

    outcome = await run_triage(model, tools=[list_attachments], budget=budget)

    assert outcome.gave_up is True
    assert outcome.reason == "The model provider could not be reached."
    # Written down as well as returned, so "why is clarification needed?" is answerable
    # from the record alone (NFR-3).
    assert [entry.observed for entry in outcome.ledger] == [
        "The model provider could not be reached."
    ]
    assert outcome.budget.steps_used == 1


async def test_a_refused_request_says_so_rather_than_blaming_the_connection() -> None:
    """NFR-4: the two kinds of model failure send a reader looking in different places."""
    model = scripted(ModelAuthenticationError("the key is wrong"))

    outcome = await run_triage(model)

    assert outcome.reason == "The model provider refused the request."


async def test_a_model_that_does_not_answer_in_time_ends_the_pass() -> None:
    """NFR-4: a timeout is named in the requirement, and it reaches a person like the rest.

    An ordinary timeout can arrive without the model library having labelled it as one of
    its own conditions, so it is handled in its own right.
    """
    model = scripted(TimeoutError("no answer"))

    outcome = await run_triage(model)

    assert outcome.gave_up is True
    assert outcome.reason == "The model provider did not answer in time."


# --- A tool that breaks its contract (FR-1.3, NFR-4) ------------------------


async def test_a_tool_that_breaks_is_reported_to_the_model_in_words_and_not_retried() -> None:
    """NFR-4: a broken tool is reported through the run, not raised, and not tried again.

    Every expected failure is caught inside the tool and answered in words, so an exception
    reaching the loop is a bug, and a bug does not mend itself on a second try.
    """
    breaks_once = a_tool_that_fails(times=1)
    model = scripted(
        asks_for("read_case", case_id="CASE-1003"),
        AIMessage(content="I will answer without it."),
        a_split(),
    )
    budget = budget_of(steps=4)

    outcome = await run_triage(model, tools=[breaks_once], budget=budget)

    assert outcome.ledger[0].succeeded is False
    # The model is told in plain words, and gets to decide what to do about it.
    assert "read case tool could not answer" in model.asked[1].text
    # The exception's own wording never reaches the model.
    assert "the read failed" not in model.asked[1].text
    assert outcome.answer == a_split()


async def test_a_tool_asked_for_with_the_wrong_arguments_is_reported_rather_than_fatal() -> None:
    """NFR-4: the model gets its own mistake back as words, and the pass carries on.

    The tool refuses the call itself, before any of its own work starts. It is reported
    the same way as a tool that broke, which is a coarse answer — the model is told the
    call did not work rather than which argument was wrong.
    """
    model = scripted(
        asks_for("inspect_image"),
        AIMessage(content="I will try that differently."),
        a_split(),
    )
    budget = budget_of(steps=4)

    outcome = await run_triage(model, tools=[inspect_image], budget=budget)

    assert outcome.ledger[0].succeeded is False
    assert outcome.ledger[0].asked == "Use the inspect image tool."
    assert "inspect image tool could not answer" in model.asked[1].text
    assert outcome.answer == a_split()


async def test_asking_for_a_tool_that_does_not_exist_is_answered_rather_than_fatal() -> None:
    """NFR-4: a tool the agent does not have is a fact to report, not a crash.

    It is deliberately not retried — the name will be missing the second time too — and
    the model is told what it does have so it can correct itself.
    """
    model = scripted(
        asks_for("send_email", to="merchant@example.test"),
        AIMessage(content="Understood."),
        a_split(),
    )
    budget = budget_of(steps=4)

    outcome = await run_triage(model, tools=[list_attachments], budget=budget)

    assert outcome.ledger[0].succeeded is False
    assert "no tool called send_email" in model.asked[1].text
    assert "list_attachments" in model.asked[1].text
    assert outcome.answer == a_split()


# --- The record and the narration (NFR-3, NFR-5) ----------------------------


async def test_every_step_is_written_down_in_the_order_it_happened() -> None:
    """NFR-3, NFR-5: the record answers what the run did, and in what order."""
    model = scripted(
        asks_for("list_attachments", call_id="call-1", case_id="CASE-1003"),
        asks_for("inspect_image", call_id="call-2", attachment_id="ATT-01"),
        "done",
        a_split(),
    )
    ledger = RunLedger()

    outcome = await run_triage(model, tools=[list_attachments, inspect_image], ledger=ledger)

    assert [entry.sequence for entry in outcome.ledger] == [1, 2, 3]
    assert [entry.name for entry in outcome.ledger] == [
        "list_attachments",
        "inspect_image",
        "ClaimSplit",
    ]
    assert [entry.kind for entry in outcome.ledger] == [
        StepKind.TOOL_CALL,
        StepKind.TOOL_CALL,
        StepKind.REASONING,
    ]
    assert outcome.ledger[0].asked == "Use the list attachments tool with case_id: CASE-1003."
    assert outcome.ledger[1].observed == "ATT-01 shows a cracked bottle"
    assert all(entry.succeeded for entry in outcome.ledger)


async def test_the_run_says_what_it_is_doing_while_it_works() -> None:
    """FR-1.1: choosing what to look at next is the thing worth showing a representative."""
    model = scripted(
        AIMessage(
            content="The first image is too dark, so I will look at the second.",
            tool_calls=[
                {
                    "name": "inspect_image",
                    "args": {"attachment_id": "ATT-02"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        ),
        "That is enough.",
        a_split(),
    )
    stream = EventStream()

    await run_triage(model, tools=[inspect_image], events=stream)

    called = events_of(stream, EventKind.TOOL_CALLED)
    assert [event.summary for event in called] == ["Used the inspect image tool."]
    assert called[0].detail == {"tool": "inspect_image", "outcome": "answered"}
    thinking = events_of(stream, EventKind.THINKING)
    assert thinking[0].summary == "The first image is too dark, so I will look at the second."


async def test_a_tool_that_could_not_answer_is_narrated_as_such() -> None:
    """NFR-4: a screen shows the failure rather than a step that appears to have worked."""
    model = scripted(asks_for("read_case", case_id="CASE-1003"), "done", a_split())
    stream = EventStream()

    await run_triage(
        model,
        tools=[a_tool_that_fails(times=99)],
        budget=budget_of(steps=4),
        events=stream,
    )

    called = events_of(stream, EventKind.TOOL_CALLED)
    assert [event.summary for event in called] == ["The read case tool could not answer."]
    assert called[0].detail["outcome"] == "failed"


async def test_a_long_remark_reaches_the_screen_whole() -> None:
    """A remark is passed on as written, however long, and with its line breaks kept.

    The end of a remark is the part saying what the run decided to do next, so cutting
    one loses exactly what somebody watching wanted to read. The line breaks matter for
    the same reason: a remark written as a list is meant to be read as a list.
    """
    remark = "Here is what I am weighing up:\n\n" + "- Another consideration.\n" * 100
    model = scripted(AIMessage(content=remark), a_split())
    stream = EventStream()

    await run_triage(model, events=stream)

    said = events_of(stream, EventKind.THINKING)[0].summary
    assert said == remark.strip()


# --- One budget per pass (FR-1.3) -------------------------------------------


async def test_each_pass_runs_on_its_own_budget() -> None:
    """FR-1.3: budgets are per run, so a claim with four products has four of them.

    Both passes here go through the same loop and end on different forms, which is the
    reuse the loop exists for. Each gets the whole allowance its policy grants.
    """
    triage_model = scripted(asks_for("list_attachments", case_id="CASE-1003"), "done", a_split())
    triage_budget = budget_of(steps=3)
    triage = await run_triage(triage_model, tools=[list_attachments], budget=triage_budget)

    line_model = scripted(asks_for("inspect_image", attachment_id="ATT-01"), "done", a_conclusion())
    line_budget = budget_of(steps=3)
    line = await run_agent_pass(
        opening_messages=[HumanMessage(content="What about this product?")],
        tools=[inspect_image],
        concludes_with=InvestigationConclusion,
        closing_request="Give your conclusion for this product.",
        chat=line_model,
        structured=StructuredModel(line_model, max_attempts=1),
        budget=line_budget,
        ledger=RunLedger(),
        events=EventStream(),
    )

    assert triage.answer == a_split()
    assert line.answer == a_conclusion()
    # Neither pass spent anything the other had.
    assert triage.budget.steps_used == 2
    assert line.budget.steps_used == 2
    assert triage.budget.steps_allowed == 3
    assert line.budget.steps_allowed == 3


async def test_a_budget_that_another_pass_already_spent_is_refused() -> None:
    """FR-1.3: sharing one budget between passes is a mistake in our code, so it is loud.

    A shared budget would leave the last product a fraction of the allowance the first
    one had, and the only sign would be unexplained representative clarification requests.
    """
    already_used = budget_of(steps=4)
    await run_triage(scripted("done", a_split()), budget=already_used)

    with pytest.raises(RuntimeError, match="already been spent"):
        await run_triage(scripted("done", a_split()), budget=already_used)


# --- The same claim, investigated twice (NFR-1) -----------------------------


async def test_the_same_script_reaches_the_same_outcome_twice() -> None:
    """NFR-1: nothing here reads a clock or a random number, so two runs match exactly."""

    async def one_run() -> LoopOutcome[ClaimSplit]:
        return await run_triage(
            scripted(
                asks_for("list_attachments", case_id="CASE-1003"),
                asks_for("inspect_image", attachment_id="ATT-01"),
                "done",
                a_split(),
            ),
            tools=[list_attachments, inspect_image],
            budget=budget_of(steps=5),
        )

    first = await one_run()
    second = await one_run()

    # Every part of it: the answer, the record of how it was reached, and what it cost.
    assert first == second


# --- A pass can continue an earlier pass's conversation (FR-R.2) -------------


async def test_a_pass_given_a_used_thread_continues_that_conversation() -> None:
    """FR-R.2: the second pass sees everything the first one saw and said, then its own turn."""
    threads = PassThreads()
    thread = threads.start("CASE-1")
    first = scripted(asks_for("list_attachments", case_id="CASE-1"), "seen enough", a_split())
    await run_agent_pass(
        opening_messages=[SystemMessage(content="The rules."), HumanMessage(content="Which?")],
        tools=[list_attachments],
        concludes_with=ClaimSplit,
        closing_request=CLOSING_REQUEST,
        chat=first,
        structured=StructuredModel(first, max_attempts=1),
        budget=budget_of(),
        ledger=RunLedger(),
        events=EventStream(),
        thread=thread,
    )
    assert await threads.remembers(thread.thread_id) is True

    second = scripted("I remember what I saw.", a_split("Continued."))
    outcome = await run_agent_pass(
        opening_messages=[HumanMessage(content="The representative says the split is wrong.")],
        tools=[list_attachments],
        concludes_with=ClaimSplit,
        closing_request=CLOSING_REQUEST,
        chat=second,
        structured=StructuredModel(second, max_attempts=1),
        budget=budget_of(),
        ledger=RunLedger(),
        events=EventStream(),
        thread=threads.resume(thread.thread_id),
    )

    assert outcome.answer is not None
    assert outcome.answer.reasoning == "Continued."
    shown = second.asked[0].text
    # The first pass's question, its tool result and its remark all precede the new turn.
    assert shown.index("The rules.") < shown.index("Which?") < shown.index("two images on CASE-1")
    assert shown.index("seen enough") < shown.index("the split is wrong")


async def test_a_pass_with_no_thread_starts_from_nothing_every_time() -> None:
    """A pass that keeps no thread is exactly the pass it was before threads existed."""
    first = scripted("done", a_split())
    await run_triage(first)
    second = scripted("done", a_split())

    await run_triage(second)

    assert second.asked[0].text.count("Which?") == 1


async def test_two_threads_never_see_each_other() -> None:
    """A fresh thread per investigation keeps two claims' evidence apart."""
    threads = PassThreads()
    one, two = threads.start("CASE-1"), threads.start("CASE-2")
    assert one.thread_id != two.thread_id
    assert await threads.remembers(None) is False
    assert await threads.remembers(two.thread_id) is False


# --- The tools of one turn run together, within a cap (FR-1.3, NFR-8) --------


async def test_the_tools_of_one_turn_are_carried_out_at_the_same_time() -> None:
    """NFR-8: independent calls in one turn do not wait for one another."""
    left, right, seen = two_tools_that_notice_each_other()
    model = scripted(asks_for_several("read_left", "read_right"), "done", a_split())

    outcome = await run_triage(model, tools=[left, right])

    assert seen["overlapped"] is True
    assert outcome.answer == a_split()
    # The answers go back in the order they were asked for, whichever finished first.
    answered = model.asked[1].text
    assert answered.index("left of CASE-1") < answered.index("right of CASE-1")


async def test_a_turn_may_not_ask_for_more_tools_than_the_cap_allows() -> None:
    """FR-1.3: a step is a turn, so a turn is held to a fixed amount of work.

    Every call still gets an answer under its own id — the provider requires one — and
    the declined ones say plainly that they can be asked for again.
    """
    model = scripted(
        asks_for_several("list_attachments", "list_attachments", "list_attachments"),
        "done",
        a_split(),
    )
    budget = RunBudget(Policy(max_agent_steps=6, max_tool_calls_per_step=2))

    outcome = await run_triage(model, tools=[list_attachments], budget=budget)

    carried_out = [entry for entry in outcome.ledger if entry.kind is StepKind.TOOL_CALL]
    assert [entry.succeeded for entry in carried_out] == [True, True, False]
    assert "a turn may use at most 2" in carried_out[2].observed
    answered = model.asked[1].text
    assert answered.count("two images on CASE-1") == 2
    assert "Ask for it again on your next turn" in answered
    assert outcome.answer == a_split()


# --- What a run cost is on the record (NFR-3) ---------------------------------


async def test_the_tokens_a_pass_spent_are_on_its_budget_snapshot() -> None:
    """NFR-3: what each model turn cost is added up on the run, from the provider's own figures."""
    model = scripted(
        AIMessage(
            content="done",
            usage_metadata={
                "input_tokens": 900,
                "output_tokens": 40,
                "total_tokens": 940,
                "input_token_details": {"cache_read": 800},
            },
        ),
        a_split(),
    )

    outcome = await run_triage(model)

    assert outcome.budget.model_calls >= 1
    assert outcome.budget.input_tokens == 900
    assert outcome.budget.output_tokens == 40
    assert outcome.budget.cache_read_tokens == 800
