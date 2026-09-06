from __future__ import annotations

from decimal import Decimal

import pytest

from claim_agent.policy import Policy


def test_reimbursement_cap_matches_stated_policy() -> None:
    assert Policy().reimbursement_cap_usd == Decimal("100.00")


def test_values_are_overridable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MAX_CLAIM_AGE_DAYS", "30")
    assert Policy().max_claim_age_days == 30


def test_precedent_similarity_threshold_is_bounded() -> None:
    with pytest.raises(ValueError, match="min_precedent_similarity"):
        Policy(min_precedent_similarity=1.5)
