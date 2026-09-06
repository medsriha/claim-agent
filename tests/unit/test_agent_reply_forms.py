from __future__ import annotations

from typing import Any

from tests.fakes.model import scripted
from tests.unit.test_agent_revise import CASE, CONTEXT, IMAGES, RECORD

from claim_agent.agent.events import EventKind, EventStream, RunEvent
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.revise import ClaimRevision, rework_claim_report
from claim_agent.agent.schemas import RevisedClaimReport, RevisionMode, RevisionPlan


def test_a_changed_list_written_as_one_sentence_is_read_as_one_item() -> None:
    answered = RevisedClaimReport.model_validate(
        {
            "reply_to_representative": "Done.",
            "changed": "Dropped the request for a photograph.",
            "left_unchanged": None,
        }
    )

    assert answered.changed == ("Dropped the request for a photograph.",)
    assert answered.left_unchanged == ()


def test_blank_entries_in_a_list_are_dropped() -> None:
    answered = RevisionPlan.model_validate(
        {
            "mode": RevisionMode.ANSWER_ONLY,
            "reply_to_representative": "The report already says so.",
            "changed": ["", None, "  Kept the figure.  "],
        }
    )

    assert answered.changed == ("Kept the figure.",)


def test_requested_details_written_as_prose_are_read_the_same_way() -> None:
    answered = RevisedClaimReport.model_validate(
        {
            "reply_to_representative": "Asking the merchant.",
            "requested_details": "A photograph of the outer box",
        }
    )

    assert answered.requested_details == ("A photograph of the outer box",)


async def answer_the_clarification(*replies: Any, events: EventStream) -> ClaimRevision:
    model = scripted(*replies)
    return await rework_claim_report(
        case_record=RECORD,
        context=CONTEXT,
        attachments=IMAGES,
        ambiguity="Two products, and no photograph tells them apart.",
        candidate_lines=(),
        requested_details=(),
        concerns=(),
        drafted_email=None,
        feedback="I confirmed it with the merchant. Go ahead and refund.",
        conversation=(),
        structured=StructuredModel(model, max_attempts=1),
        events=events,
    )


async def test_an_answer_that_does_not_fit_is_asked_for_once_more() -> None:
    seen: list[RunEvent] = []

    async def keep(event: RunEvent) -> None:
        seen.append(event)

    revision = await answer_the_clarification(
        {"not": "a form at all"},
        RevisedClaimReport(reply_to_representative="Taken as read; pricing it now."),
        events=EventStream(sink=keep),
    )

    assert revision.reply == "Taken as read; pricing it now."
    assert any(
        event.kind is EventKind.THINKING and "did not fit" in event.summary for event in seen
    )


async def test_the_correction_tells_the_model_what_was_wrong() -> None:
    model = scripted(
        {"not": "a form at all"},
        RevisedClaimReport(reply_to_representative="Taken as read."),
    )

    await rework_claim_report(
        case_record=RECORD,
        context=CONTEXT,
        attachments=IMAGES,
        ambiguity="Two products.",
        candidate_lines=(),
        requested_details=(),
        concerns=(),
        drafted_email=None,
        feedback="Go ahead and refund.",
        conversation=(),
        structured=StructuredModel(model, max_attempts=1),
        events=EventStream(),
    )

    assert len(model.asked) == 2
    assert "did not fit the form" in model.asked[1].text
    assert "Lists are lists of short strings" in model.asked[1].text


async def test_a_second_answer_that_does_not_fit_still_leaves_a_reply() -> None:
    revision = await answer_the_clarification(
        {"not": "a form"}, {"still": "not a form"}, events=EventStream()
    )

    assert "could not be reworked" in revision.reply
    assert CASE.case_id
