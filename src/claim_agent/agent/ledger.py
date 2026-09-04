"""The ordered record of what one investigation actually did (NFR-3, NFR-5).

A support representative is the one who decides what happens to a claim, so she
has to be able to audit what she is being asked to decide on. That means "why
this amount?" and "why was this escalated?" have to be answerable from the result
she is handed — not by opening a log file, and not by running the investigation
again and hoping it does the same thing. This file is the record that makes that
possible: one entry per thing the run did, in the order it did them, each saying
what was asked, what came back, and whether it worked.

It is also the beginning of the audit trail REQUIREMENTS.md asks for (NFR-5).
Only the beginning: an audit trail has to survive a restart, and this does not.

**Everything here is safe to hand back over the API.** That is a rule about what
may be written into an entry, not a hope. An entry holds a short sentence and an
identifier — the id of the attachment that was looked at, the name of the form
the model was asked to fill in. It never holds a credential, the bytes of an
image, or a raw model transcript. Anything over-long is trimmed rather than
refused, because a run must not fail over the wording of its own record.

**Nothing here is stored.** A ledger is built when a run starts, lives as long as
the response that carries it, and is then thrown away with the rest of the run.
There is no table behind it and no file. That is a gap rather than a design: the
audit trail NFR-5 describes is meant to be kept, and this one is not.

**No clock is read in here.** Ordering comes from a sequence number that goes up
by one each time, which is enough to answer "what happened, and in what order"
and cannot come out differently on two runs. Wall-clock time is optional and,
where it is wanted, is handed in by the caller — exactly as the pre-flight screen
takes the moment it was asked for rather than looking it up (see the note on
`evaluated_at` in `claim_agent.preflight.service`). Keeping the one impure moment
out at the edge is what lets a test compare two runs of the same claim and expect
the same record (NFR-1).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import UtcDatetime
from claim_agent.observability import get_logger

logger = get_logger(__name__)

MAX_SUMMARY_CHARACTERS = 300
"""How long the two written parts of an entry may be.

Long enough for a sentence or two, which is all a record of one step should be,
and short enough that a whole run's ledger stays readable and stays a summary
rather than a copy of what the run saw. Text over this length is cut and marked
with an ellipsis.
"""


class StepKind(StrEnum):
    """The two kinds of thing an investigation step can be.

    Kept coarse on purpose. The interesting detail — which tool, which form — is
    the entry's `name`, and a long list of kinds would only be a second place for
    that same detail to be written down and to disagree with itself.

    `TOOL_CALL` is the run using one of the tools it is allowed: listing a case's
    attachments, looking at an image, generating an invoice, working out a
    reimbursement (FR-1.2). `REASONING` is the run asking the model to fill in one
    of the forms in `claim_agent.agent.schemas` (NFR-2).
    """

    TOOL_CALL = "tool_call"
    REASONING = "reasoning"


class LedgerEntry(BaseModel):
    """One thing a run did, written down so someone else can follow it (NFR-3).

    Frozen, because a record that can be edited afterwards is not a record.

    Fields:
        sequence: Where this step came in the run, counting from one. This is the
            only ordering there is, and it is what makes the record comparable
            between two runs of the same claim.
        kind: Whether the run used a tool or asked the model something.
        name: Which tool or which form, in the words the code uses for it, so a
            reader can go and find it.
        asked: What the run wanted, in one plain sentence.
        observed: A short account of what came back. On a step that failed, this
            says what went wrong, in words rather than an exception.
        succeeded: Whether the step did what it set out to do. A failed step stays
            in the record; leaving it out would make a run look tidier than it was
            and would hide the reason it escalated (NFR-4).
        reference: The identifier of the thing the step was about — an attachment
            id, a shipment id — so a representative can look at the same thing the
            system did. `None` when the step was not about one particular thing.
        at: When the step happened, if the caller said. `None` means nobody
            supplied a moment, which is the normal case today because nothing
            reads a clock for this. The order is still exact either way.
    """

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
    """The growing, ordered list of what one run has done (NFR-3, NFR-5).

    Build one at the start of a run, alongside its budget, and let it be thrown
    away with the run. Like the budget it belongs to one run and is not
    thread-safe: one run does one thing at a time.

    **Append-only.** There is no way to remove or rewrite an entry, and the list
    handed out by `entries` is a copy, so a caller that has been given the record
    cannot quietly change it. That is the whole value of the thing: a record a
    later step could edit would not be evidence of anything.

    A ledger with no entries is an ordinary state, not an error — it is what a run
    that failed before it did anything leaves behind, and a report should say so
    plainly rather than pretending the run never happened.
    """

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
        """Write down one step and return the entry that was written.

        The sequence number is assigned here, so a caller cannot get the ordering
        wrong and two callers cannot claim the same position.

        `asked` and `observed` are trimmed to `MAX_SUMMARY_CHARACTERS`. Write a
        sentence, not a payload: the id of what was looked at goes in `reference`,
        and the thing itself does not go in at all.

        Args:
            kind: Whether the run used a tool or asked the model something.
            name: Which tool or which form.
            asked: What the run wanted, in one plain sentence.
            observed: A short account of what came back, or of what went wrong.
            succeeded: Whether the step did what it set out to do.
            reference: The id of the thing the step was about, if there was one.
            at: When it happened, if the caller knows and cares to say. Nothing
                here reads a clock, so this is the only way a time gets in.

        Returns:
            The entry as it was recorded, sequence number and trimming included.
        """
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
        """Hand back every step in the order it happened.

        A tuple rather than the list itself, so nothing outside can add to,
        reorder, or drop from the record. Empty when the run has done nothing yet.
        """
        return tuple(self._entries)

    def failures(self) -> tuple[LedgerEntry, ...]:
        """Hand back only the steps that did not work, in order.

        This is the short answer to "why was this escalated?": a run that could
        not read an attachment or could not get a usable answer from the model has
        that written here, and the explanation a representative is given can be
        built from it rather than from prose someone wrote by hand (NFR-3, NFR-4).
        Empty when every step worked.
        """
        return tuple(entry for entry in self._entries if not entry.succeeded)

    def __len__(self) -> int:
        """How many steps have been recorded. Lets a caller write `len(ledger)`."""
        return len(self._entries)


def _shortened(text: str) -> str:
    """Cut a written summary down to the length an entry allows.

    Cut rather than refused: the ledger exists to explain a run, and a run that
    fell over because its own note about itself was too long would be absurd. The
    ellipsis is there so a reader can tell the sentence was cut and is not simply
    an odd thing for the system to have said.
    """
    if len(text) <= MAX_SUMMARY_CHARACTERS:
        return text
    return text[: MAX_SUMMARY_CHARACTERS - 1] + "…"
