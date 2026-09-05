from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from claim_agent.live_policy import LivePolicy
from claim_agent.policy import Policy

A_MOMENT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
A_LATER_MOMENT = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)


def test_it_starts_on_the_policy_it_was_given() -> None:
    """FR-0.7: before anyone changes anything, the startup values are in force."""
    startup = Policy(max_claim_age_days=60)

    live = LivePolicy(startup)

    assert live.current() is startup
    assert live.startup_policy is startup
    assert live.changed_at is None


def test_a_change_is_in_force_for_the_next_claim() -> None:
    """FR-0.7: whoever asks next gets the new values, with no restart in between."""
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    assert live.current().max_claim_age_days == 5
    assert live.changed_at == A_MOMENT


def test_a_policy_already_handed_out_is_not_changed_underneath_its_reader() -> None:
    """FR-0.6: a claim being judged finishes on the values it started with.

    Screening reads the policy once and passes that one answer to all four checks.
    A change landing halfway through must not reach it, or a claim ends up judged
    partly by one age limit and partly by another — an answer nobody could explain
    afterwards.
    """
    live = LivePolicy(Policy(max_claim_age_days=60))
    being_used_right_now = live.current()

    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    assert being_used_right_now.max_claim_age_days == 60


def test_saving_the_same_values_again_does_not_claim_a_change_happened() -> None:
    """FR-0.7: submitting a form nobody edited is allowed, and dates nothing.

    "In force since" has to mean what it says, so it only moves when the values
    actually differ.
    """
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=60), changed_at=A_MOMENT)

    assert live.changed_at is None
    assert live.current().max_claim_age_days == 60


def test_the_moment_moves_with_each_real_change() -> None:
    """FR-0.7: the recorded moment is the last one that changed something."""
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=30), changed_at=A_MOMENT)
    live.replace(Policy(max_claim_age_days=15), changed_at=A_LATER_MOMENT)

    assert live.changed_at == A_LATER_MOMENT


def test_reset_puts_back_the_startup_values_and_forgets_the_change() -> None:
    """FR-0.7: reset leaves the service as though nobody had touched the policy."""
    startup = Policy(max_claim_age_days=60, reimbursement_cap_usd=Decimal("100.00"))
    live = LivePolicy(startup)
    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    live.reset()

    assert live.current() is startup
    assert live.changed_at is None
