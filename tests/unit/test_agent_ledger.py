from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from claim_agent.agent.ledger import MAX_SUMMARY_CHARACTERS, RunLedger, StepKind

A_MOMENT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
A_LATER_MOMENT = datetime(2026, 1, 1, 9, 5, tzinfo=UTC)


def test_a_run_that_did_nothing_leaves_an_empty_record() -> None:
    ledger = RunLedger()

    assert ledger.entries() == ()
    assert ledger.failures() == ()
    assert len(ledger) == 0


def test_each_step_is_written_down_in_the_order_it_happened() -> None:
    ledger = RunLedger()

    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="list_attachments",
        asked="List the images on this case.",
        observed="Four images.",
        succeeded=True,
    )
    ledger.record(
        kind=StepKind.REASONING,
        name="ClaimSplit",
        asked="Which products is this claim for?",
        observed="One product, the 24oz bottle.",
        succeeded=True,
    )

    assert [entry.sequence for entry in ledger.entries()] == [1, 2]
    assert [entry.name for entry in ledger.entries()] == ["list_attachments", "ClaimSplit"]
    assert len(ledger) == 2


def test_the_sequence_number_is_assigned_by_the_ledger() -> None:
    ledger = RunLedger()

    entry = ledger.record(
        kind=StepKind.TOOL_CALL,
        name="inspect_image",
        asked="What does this photograph show?",
        observed="A crushed carton.",
        succeeded=True,
    )

    assert entry.sequence == 1
    assert ledger.entries() == (entry,)


def test_ordering_does_not_depend_on_a_clock() -> None:
    first = RunLedger()
    second = RunLedger()
    for ledger in (first, second):
        ledger.record(
            kind=StepKind.TOOL_CALL,
            name="list_attachments",
            asked="List the images on this case.",
            observed="Four images.",
            succeeded=True,
        )

    assert first.entries() == second.entries()
    assert first.entries()[0].at is None


def test_a_moment_is_recorded_only_when_the_caller_supplies_one() -> None:
    ledger = RunLedger()

    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="generate_invoice",
        asked="Generate the invoice for this shipment.",
        observed="An invoice for three lines.",
        succeeded=True,
        at=A_MOMENT,
    )
    ledger.record(
        kind=StepKind.REASONING,
        name="InvestigationConclusion",
        asked="What do you recommend for this line?",
        observed="Request representative clarification: the packaging photograph is missing.",
        succeeded=True,
        at=A_LATER_MOMENT,
    )

    assert [entry.at for entry in ledger.entries()] == [A_MOMENT, A_LATER_MOMENT]


def test_a_failed_step_stays_in_the_record() -> None:
    ledger = RunLedger()

    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="inspect_image",
        asked="What does this photograph show?",
        observed="The image could not be downloaded.",
        succeeded=False,
        reference="ATT-9001",
    )

    entry = ledger.entries()[0]
    assert entry.succeeded is False
    assert entry.observed == "The image could not be downloaded."
    assert entry.reference == "ATT-9001"


def test_the_failed_steps_can_be_read_on_their_own() -> None:
    ledger = RunLedger()

    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="list_attachments",
        asked="List the images on this case.",
        observed="Four images.",
        succeeded=True,
    )
    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="inspect_image",
        asked="What does this photograph show?",
        observed="The image could not be downloaded.",
        succeeded=False,
    )

    assert [entry.sequence for entry in ledger.failures()] == [2]

    assert len(ledger) == 2


def test_a_run_where_everything_worked_has_no_failures_to_report() -> None:
    ledger = RunLedger()

    ledger.record(
        kind=StepKind.REASONING,
        name="ClaimSplit",
        asked="Which products is this claim for?",
        observed="One product, the 24oz bottle.",
        succeeded=True,
    )

    assert ledger.failures() == ()
    assert len(ledger) == 1


def test_the_record_handed_out_cannot_be_changed_from_outside() -> None:
    ledger = RunLedger()
    ledger.record(
        kind=StepKind.TOOL_CALL,
        name="list_attachments",
        asked="List the images on this case.",
        observed="Four images.",
        succeeded=True,
    )

    handed_out = ledger.entries()
    assert isinstance(handed_out, tuple)

    with pytest.raises(ValidationError):
        cast(Any, handed_out[0]).observed = "Something else entirely."

    assert ledger.entries()[0].observed == "Four images."


def test_an_over_long_account_is_trimmed_rather_than_refused() -> None:
    ledger = RunLedger()

    entry = ledger.record(
        kind=StepKind.REASONING,
        name="InvestigationConclusion",
        asked="a" * (MAX_SUMMARY_CHARACTERS + 500),
        observed="b" * (MAX_SUMMARY_CHARACTERS + 500),
        succeeded=True,
    )

    assert len(entry.asked) == MAX_SUMMARY_CHARACTERS
    assert len(entry.observed) == MAX_SUMMARY_CHARACTERS

    assert entry.asked.endswith("…")
    assert entry.observed.endswith("…")


def test_an_account_that_already_fits_is_left_exactly_as_written() -> None:
    ledger = RunLedger()

    entry = ledger.record(
        kind=StepKind.TOOL_CALL,
        name="inspect_image",
        asked="What does this photograph show?",
        observed="A crushed carton with the seal broken.",
        succeeded=True,
    )

    assert entry.asked == "What does this photograph show?"
    assert entry.observed == "A crushed carton with the seal broken."


def test_a_step_that_was_not_about_one_particular_thing_has_no_reference() -> None:
    ledger = RunLedger()

    entry = ledger.record(
        kind=StepKind.REASONING,
        name="ClaimSplit",
        asked="Which products is this claim for?",
        observed="One product, the 24oz bottle.",
        succeeded=True,
    )

    assert entry.reference is None


def test_a_ledger_cannot_have_entries_removed_or_rewritten() -> None:
    ledger = RunLedger()

    assert not hasattr(ledger, "remove")
    assert not hasattr(ledger, "clear")
    assert not hasattr(ledger, "replace")


def test_every_run_gets_its_own_record() -> None:
    first_line = RunLedger()
    second_line = RunLedger()

    first_line.record(
        kind=StepKind.TOOL_CALL,
        name="inspect_image",
        asked="What does this photograph show?",
        observed="A crushed carton.",
        succeeded=True,
    )

    assert len(first_line) == 1
    assert second_line.entries() == ()
