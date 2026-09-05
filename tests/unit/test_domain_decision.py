from __future__ import annotations

from decimal import Decimal

from tests.fixtures.decisions import investigated, screened

from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.outcome import Recommendation

# --- Agreeing, and the difference between substance and wording (FR-2.8, FR-C.2) ---


def test_an_untouched_approval_is_a_direct_approval() -> None:
    """The plain case: nothing changed, so nobody had to do anything but read it."""
    decision = investigated()

    assert decision.is_direct_approval
    assert decision.agreed_with_recommendation
    assert not decision.outcome_changed
    assert not decision.amount_changed


def test_rewriting_the_email_is_not_a_direct_approval_but_is_still_agreement() -> None:
    """FR-2.8 separates wording from substance, and so does this.

    Rewriting the email took a representative's attention, so it is not the untouched case. It
    says nothing about whether the system reached the right answer, so it is still agreement.
    """
    decision = investigated(email_edited=True)

    assert not decision.is_direct_approval
    assert decision.agreed_with_recommendation


def test_changing_the_outcome_is_neither_direct_nor_agreement() -> None:
    """The serious kind of disagreement: the answer itself was wrong."""
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None),
    )

    assert decision.outcome_changed
    assert not decision.is_direct_approval
    assert not decision.agreed_with_recommendation


def test_changing_only_the_amount_is_disagreement_without_the_outcome_changing() -> None:
    """The judgement stood; something it was given did not.

    Kept apart from an outcome change on purpose — the two point at different faults, and the
    screen reports them separately so a reader can tell "the answer was wrong" from "the answer
    was right and the figure was not".
    """
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("15.60")),
    )

    assert decision.amount_changed
    assert not decision.outcome_changed
    assert not decision.agreed_with_recommendation


def test_an_amount_appearing_where_there_was_none_counts_as_changed() -> None:
    """Nothing to something is a change, and reporting it as unchanged would hide a payment."""
    decision = investigated(
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=None),
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    assert decision.amount_changed


def test_sending_a_report_back_is_never_agreement() -> None:
    """FR-R.1: it went back because it was not usable as it arrived."""
    decision = investigated(action=RepAction.SENT_BACK, rep_words="Check the second image.")

    assert not decision.agreed_with_recommendation
    assert not decision.is_direct_approval


# --- A claim the quick checks stopped (FR-C.1) ---


def test_a_stopped_claim_compares_no_outcomes() -> None:
    """FR-C.1: a stopped claim records the same way as any other, with nothing invented.

    It never reaches the split into products, so there is no outcome on either side to
    compare. It must not report a change it cannot have had.
    """
    decision = screened()

    assert decision.stated_confidence is None
    assert not decision.outcome_changed
    assert decision.is_direct_approval


def test_nobody_is_ever_named_as_having_decided() -> None:
    """FR-C.1: there is no sign-in, so the field exists and is left empty rather than guessed."""
    assert investigated().decided_by is None
    assert screened().decided_by is None
