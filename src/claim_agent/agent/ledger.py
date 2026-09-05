"""The ordered record of what one investigation actually did (NFR-3, NFR-5)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import UtcDatetime
from claim_agent.observability import get_logger

logger = get_logger(__name__)

# How long the two written parts of an entry may be.
MAX_SUMMARY_CHARACTERS = 300


class StepKind(StrEnum):
    """The two kinds of thing an investigation step can be."""

    TOOL_CALL = "tool_call"
    REASONING = "reasoning"


class LedgerEntry(BaseModel):
    """One thing a run did, written down so someone else can follow it (NFR-3)."""

    model_config = ConfigDict(frozen=True)

    sequence: int
    kind: StepKind
    name: str
    asked: str
    observed: str
    succeeded: bool
    reference: str | None = None
    at: UtcDatetime | None = None


class RunLedger:
    """The growing, ordered list of what one run has done (NFR-3, NFR-5)."""

    def __init__(self) -> None:
        """Open an empty ledger for one run."""
        self._entries: list[LedgerEntry] = []

    def record(
        self,
        *,
        kind: StepKind,
        name: str,
        asked: str,
        observed: str,
        succeeded: bool,
        reference: str | None = None,
        at: UtcDatetime | None = None,
    ) -> LedgerEntry:
        """Write down one step and return the entry that was written."""
        entry = LedgerEntry(
            sequence=len(self._entries) + 1,
            kind=kind,
            name=name,
            asked=_shortened(asked),
            observed=_shortened(observed),
            succeeded=succeeded,
            reference=reference,
            at=at,
        )
        self._entries.append(entry)
        # The prose belongs in the record a representative reads, not in the logs;
        # what the logs want is enough to line a run up against them.
        logger.info(
            "agent_step",
            sequence=entry.sequence,
            kind=entry.kind.value,
            name=entry.name,
            succeeded=entry.succeeded,
            reference=entry.reference,
        )
        return entry

    def entries(self) -> tuple[LedgerEntry, ...]:
        """Hand back every step in the order it happened."""
        return tuple(self._entries)

    def failures(self) -> tuple[LedgerEntry, ...]:
        """Hand back only the steps that did not work, in order."""
        return tuple(entry for entry in self._entries if not entry.succeeded)

    def __len__(self) -> int:
        """How many steps have been recorded. Lets a caller write `len(ledger)`."""
        return len(self._entries)


def _shortened(text: str) -> str:
    """Cut a written summary down to the length an entry allows."""
    if len(text) <= MAX_SUMMARY_CHARACTERS:
        return text
    return text[: MAX_SUMMARY_CHARACTERS - 1] + "…"
