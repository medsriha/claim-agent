from __future__ import annotations

from decimal import Decimal

from tests.fixtures.decisions import investigated, screened

from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.outcome import Recommendation


def test_an_untouched_approval_is_a_direct_approval() -> None:
    decision = investigated()

    assert decision.is_direct_approval
    assert decision.agreed_with_recommendation
    assert not decision.outcome_changed
    assert not decision.amount_changed


def test_rewriting_the_email_is_not_a_direct_approval_but_is_still_agreement() -> None:
    decision = investigated(email_edited=True)

    assert not decision.is_direct_approval
    assert decision.agreed_with_recommendation


def test_changing_the_outcome_is_neither_direct_nor_agreement() -> None:
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None),
    )

    assert decision.outcome_changed
    assert not decision.is_direct_approval
    assert not decision.agreed_with_recommendation


def test_changing_only_the_amount_is_disagreement_without_the_outcome_changing() -> None:
    decision = investigated(
        action=RepAction.APPROVED_WITH_OVERRIDE,
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("15.60")),
    )

    assert decision.amount_changed
    assert not decision.outcome_changed
    assert not decision.agreed_with_recommendation


def test_an_amount_appearing_where_there_was_none_counts_as_changed() -> None:
    decision = investigated(
        recommended=Proposal(outcome=Recommendation.APPROVE, amount_usd=None),
        decided=Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
    )

    assert decision.amount_changed


def test_sending_a_report_back_is_never_agreement() -> None:
    decision = investigated(action=RepAction.SENT_BACK, rep_words="Check the second image.")

    assert not decision.agreed_with_recommendation
    assert not decision.is_direct_approval


def test_a_stopped_claim_compares_no_outcomes() -> None:
    decision = screened()

    assert decision.stated_confidence is None
    assert not decision.outcome_changed
    assert decision.is_direct_approval


def test_nobody_is_ever_named_as_having_decided() -> None:
    assert investigated().decided_by is None
    assert screened().decided_by is None
