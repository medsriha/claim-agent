from __future__ import annotations

from decimal import Decimal

from tests.fixtures.decisions import investigated, screened

from claim_agent.domain.correction import correction_from
from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.outcome import Recommendation

# --- Only a difference is remembered (FR-C.2) --------------------------------


def test_agreeing_with_the_recommendation_writes_nothing() -> None:
    """FR-C.2: a memory of every decision is a memory of nothing.

    Notes saying a representative agreed would fill the next claim's context with confirmations
    and bury the one correction that mattered.
    """
    assert correction_from(investigated()) is None


def test_rewording_the_email_alone_writes_nothing() -> None:
    """FR-2.8, FR-C.2: rewording is about how an email reads, not about what the answer was."""
    assert correction_from(investigated(email_edited=True)) is None


def test_a_stopped_claim_approved_as_it_stood_writes_nothing() -> None:
    """A claim the quick checks turned away has no outcome and no figure to disagree about."""
    assert correction_from(screened()) is None


# --- What the sentence says (FR-C.2) -----------------------------------------


def test_a_changed_amount_names_both_figures() -> None:
    """FR-C.2: enough words for the next investigation to act on, which means the numbers."""
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("18.00")),
    )

    written = correction_from(decision)

    assert written is not None
    assert "$31.20" in written
    assert "$18.00" in written


def test_a_changed_outcome_says_what_was_advised_and_what_was_done() -> None:
    """The serious disagreement: the answer itself was wrong, so both answers are named."""
    decision = investigated(
        recommended=Proposal(outcome=Recommendation.REQUEST_INFO, amount_usd=None),
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    written = correction_from(decision)

    assert written is not None
    assert "going back to the merchant" in written
    assert "approved it" in written
    assert "$31.20" in written


def test_an_amount_is_written_as_exact_money_and_never_through_a_float() -> None:
    """FR-1.21: money is read and written as an exact decimal, cents intact."""
    decision = investigated(
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00")),
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.2")),
    )

    written = correction_from(decision)

    assert written is not None
    assert "$52.00" in written
    assert "$31.20" in written


def test_a_representative_who_explained_themselves_is_quoted() -> None:
    """Their words are worth more than ours; ours carry the figures, so both are kept."""
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("18.00")),
        rep_words="Only the two-pack was damaged, not the single bottle.",
    )

    written = correction_from(decision)

    assert written is not None
    assert "$18.00" in written
    assert "Only the two-pack was damaged, not the single bottle." in written


def test_words_that_are_only_spaces_are_not_quoted() -> None:
    """An empty quotation reads as though somebody said nothing, which is worse than silence."""
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("18.00")),
        rep_words="   ",
    )

    written = correction_from(decision)

    assert written is not None
    assert "They said" not in written


def test_paying_nothing_after_being_advised_to_pay_reads_as_nothing() -> None:
    """A representative who refused a payment the system advised is a correction worth keeping."""
    decision = investigated(
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.REQUEST_INFO, amount_usd=None),
    )

    written = correction_from(decision)

    assert written is not None
    assert "went back to the merchant" in written
    assert "paid" not in written
