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
    # FR-0.7: the policy it was built with is the one in force, and the one a reset
    # goes back to. The app holds the changeable policy rather than a bare one,
    # because the admin panel can replace it while the service runs.
    assert app.state.live_policy.current() is policy
    assert app.state.live_policy.startup_policy is policy
