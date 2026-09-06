from __future__ import annotations

from decimal import Decimal

from claim_agent.app import create_app
from claim_agent.policy import Policy
from claim_agent.settings import Settings


def test_app_uses_the_settings_and_policy_it_was_built_with() -> None:
    settings = Settings(environment="test")
    policy = Policy(reimbursement_cap_usd=Decimal("250.00"))

    app = create_app(settings, policy)

    assert app.state.settings is settings

    assert app.state.live_policy.current() is policy
    assert app.state.live_policy.startup_policy is policy
