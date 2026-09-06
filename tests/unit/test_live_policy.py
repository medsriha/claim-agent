from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from claim_agent.live_policy import LivePolicy
from claim_agent.policy import Policy

A_MOMENT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
A_LATER_MOMENT = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)


def test_it_starts_on_the_policy_it_was_given() -> None:
    startup = Policy(max_claim_age_days=60)

    live = LivePolicy(startup)

    assert live.current() is startup
    assert live.startup_policy is startup
    assert live.changed_at is None


def test_a_change_is_in_force_for_the_next_claim() -> None:
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    assert live.current().max_claim_age_days == 5
    assert live.changed_at == A_MOMENT


def test_a_policy_already_handed_out_is_not_changed_underneath_its_reader() -> None:
    live = LivePolicy(Policy(max_claim_age_days=60))
    being_used_right_now = live.current()

    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    assert being_used_right_now.max_claim_age_days == 60


def test_saving_the_same_values_again_does_not_claim_a_change_happened() -> None:
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=60), changed_at=A_MOMENT)

    assert live.changed_at is None
    assert live.current().max_claim_age_days == 60


def test_the_moment_moves_with_each_real_change() -> None:
    live = LivePolicy(Policy(max_claim_age_days=60))

    live.replace(Policy(max_claim_age_days=30), changed_at=A_MOMENT)
    live.replace(Policy(max_claim_age_days=15), changed_at=A_LATER_MOMENT)

    assert live.changed_at == A_LATER_MOMENT


def test_reset_puts_back_the_startup_values_and_forgets_the_change() -> None:
    startup = Policy(max_claim_age_days=60, reimbursement_cap_usd=Decimal("100.00"))
    live = LivePolicy(startup)
    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    live.reset()

    assert live.current() is startup
    assert live.changed_at is None
