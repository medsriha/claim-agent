from __future__ import annotations

from datetime import datetime

from claim_agent.policy import Policy


class LivePolicy:
    """Holds the policy claims are judged by, and swaps in a new one on request."""

    def __init__(self, startup_policy: Policy) -> None:
        """Start with the policy the service booted on."""
        self._startup_policy = startup_policy
        self._current = startup_policy
        self._changed_at: datetime | None = None

    @property
    def startup_policy(self) -> Policy:
        """The policy this process started with, whatever has happened since."""
        return self._startup_policy

    @property
    def changed_at(self) -> datetime | None:
        """When the values in force last actually changed."""
        return self._changed_at

    def current(self) -> Policy:
        """Return the policy in force, for one claim to be judged by."""
        return self._current

    def replace(self, policy: Policy, *, changed_at: datetime) -> None:
        """Put a new policy in force, for every claim screened from now on."""
        if policy == self._current:
            return
        self._current = policy
        self._changed_at = changed_at

    def reset(self) -> None:
        """Put back the values the service started with, as if nobody had touched it."""
        self._current = self._startup_policy
        self._changed_at = None
