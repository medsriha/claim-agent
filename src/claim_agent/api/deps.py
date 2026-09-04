"""Request-scoped dependencies.

Settings and policy are read off `app.state`, not from the module-level caches,
so a test (or a second app in the same process) can build an application with
different values and have every route see them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from claim_agent.policy import Policy
from claim_agent.settings import Settings


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_policy(request: Request) -> Policy:
    """Return the claim policy the running app was built with."""
    policy: Policy = request.app.state.policy
    return policy


SettingsDep = Annotated[Settings, Depends(get_settings)]
PolicyDep = Annotated[Policy, Depends(get_policy)]
