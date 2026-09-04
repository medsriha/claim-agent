"""The claim policy in force right now, and the one place a change to it lands.

`claim_agent.policy` says what the thresholds *are* and where their starting
values come from. This module answers a different question: which policy is the
service judging claims by at this moment, given that someone can change one from
the admin panel while the service is running (FR-0.7, NFR-7).

Two promises are worth understanding before reading the code, because the shape
of the class exists to keep them:

- **A policy is replaced whole, never edited value by value.** A claim judged
  half by the old age limit and half by the new one could not be explained
  afterwards, and editing in place is how that happens.
- **A claim reads the policy once.** Screening asks for the policy when the
  request arrives and passes that one answer to all four checks, so a change
  landing midway through a screening cannot affect it. The claim after it sees
  the new values.

Nothing here is written to disk. A change lives in the running process, and a
restart puts every value back to whatever the environment says — deliberate for a
demonstration, and listed in DESIGN.md under "Future production" as the trap it
would be in anything longer-lived.
"""

from __future__ import annotations

from datetime import datetime

from claim_agent.policy import Policy


class LivePolicy:
    """Holds the policy claims are judged by, and swaps in a new one on request.

    One of these is built when the service starts and lives as long as the
    process. Screening reads from it; the admin panel writes to it. It stores
    nothing and validates nothing — a `Policy` handed to `replace` has already
    been checked by the time it arrives, because building one is what checks it.
    """

    def __init__(self, startup_policy: Policy) -> None:
        """Start with the policy the service booted on.

        Args:
            startup_policy: The policy read from the environment, or the built-in
                defaults. Kept as well as used, because `reset` puts it back and
                the panel shows each value's starting point beside its current
                one.
        """
        self._startup_policy = startup_policy
        self._current = startup_policy
        self._changed_at: datetime | None = None

    @property
    def startup_policy(self) -> Policy:
        """The policy this process started with, whatever has happened since."""
        return self._startup_policy

    @property
    def changed_at(self) -> datetime | None:
        """When the values in force last actually changed.

        `None` means they are still the ones the service started with — either
        nobody has changed anything, or a change was reset.
        """
        return self._changed_at

    def current(self) -> Policy:
        """Return the policy in force, for one claim to be judged by.

        Callers keep the answer for the whole piece of work rather than asking
        again, which is what stops a threshold changing midway through judging a
        claim (FR-0.6).
        """
        return self._current

    def replace(self, policy: Policy, *, changed_at: datetime) -> None:
        """Put a new policy in force, for every claim screened from now on.

        The swap is a single assignment on purpose: at no point is there a policy
        made of some old values and some new ones.

        The moment is only recorded when the new values genuinely differ from the
        ones in force. Saving a form nobody edited is a reasonable thing to do,
        and it should not make "in force since" claim a change that did not
        happen.

        Args:
            policy: The policy to judge later claims by. Already valid — the only
                way to have one is to have built it, and building it is what
                checks it.
            changed_at: When the change was asked for. The caller reads the clock
                and passes the moment in, the same way screening does, so that
                nothing below the edge of the service depends on the time.
        """
        if policy == self._current:
            return
        self._current = policy
        self._changed_at = changed_at

    def reset(self) -> None:
        """Put back the values the service started with, as if nobody had touched it.

        The record of when the policy changed goes too: there is no change left to
        date.
        """
        self._current = self._startup_policy
        self._changed_at = None
