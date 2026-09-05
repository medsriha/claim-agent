"""Whether there is enough evidence to recommend anything yet, and what to ask for if not.

`evidence.py` already knows the four things a reimbursement decision needs, and already
knows the four states one of them can be in — present, missing, unusable, or unreadable.
This module adds nothing new to either list. It only answers the question a rep and a
merchant both actually want answered: given what was found, is a recommendation
supportable, and if not, what — specifically — should happen next?

CASE-1005 is the case that makes this worth writing down on its own. It has **zero
attachments** and its status is already "Waiting on Client" — nobody has sent anything
yet. The right output for a claim like that is not a priced verdict and not a vague
"insufficient evidence"; it is a specific, sendable request: which of the four things is
missing, and what exactly to ask the merchant for.

**The distinction this module exists to protect is the one `agent/tools.py`'s own module
docstring already draws, and it is repeated here rather than reinvented:** evidence the
merchant never sent, or sent too dark or blurry to use, is *their* gap and they can be
asked to fix it (FR-1.5, FR-1.6, FR-1.7). Evidence *we* could not fetch or could not get
an answer about is a fault on our side, the merchant can do nothing about it, and asking
them to "resend" something our own systems failed to read would be asking them to fix a
problem that was never theirs (NFR-4). The two must never appear in the same list of
things to ask the merchant for.

`(no requirement covers this exact shape; see DESIGN.md)`. Assembling a rep-facing
verdict from `evidence.py`'s findings is new; FR-1.6 and FR-1.7 are the requirements it
serves, and NFR-4 ("fail toward the human") is why unreadable evidence escalates instead
of being asked for again.

Nothing here reaches out to anything or reads a clock. The same findings always produce
the same verdict (NFR-1).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.evidence import (
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
    all_present,
    findings_by_kind,
    gaps_the_merchant_can_fill,
    gaps_we_caused,
)

_ASK_FOR: dict[EvidenceKind, str] = {
    EvidenceKind.INVOICE: (
        "a copy of the invoice or receipt showing what was ordered and what it cost"
    ),
    EvidenceKind.CUSTOMER_CONFIRMATION: (
        "a message from the customer confirming the parcel arrived damaged"
    ),
    EvidenceKind.DAMAGED_PRODUCT_PHOTO: "a photograph of the damaged product itself",
    EvidenceKind.OUTER_PACKAGING_PHOTO: (
        "a photograph of the outer box the order arrived in, even if the box itself looks fine"
    ),
}
"""What to ask the merchant for, per kind of evidence — specific enough to send as-is.

The packaging line spells out that the box need not itself be damaged, because
`evidence.py` is explicit that an intact box around a broken product is still a
legitimate claim (FR-1.11); a rep copying this sentence should not accidentally imply
otherwise to the merchant.
"""

_LABEL: dict[EvidenceKind, str] = {
    EvidenceKind.INVOICE: "the invoice",
    EvidenceKind.CUSTOMER_CONFIRMATION: "the customer's confirmation that it arrived damaged",
    EvidenceKind.DAMAGED_PRODUCT_PHOTO: "a photograph of the damaged product",
    EvidenceKind.OUTER_PACKAGING_PHOTO: "a photograph of the outer box",
}
"""Short names for each kind of evidence, for the one-sentence summary rather than the
specific request — `_ASK_FOR` is what gets sent to a merchant, this is what a rep reads.
"""


class SufficiencyAssessment(BaseModel):
    """Whether the evidence gathered so far can support a recommendation, and what to do next.

    Attributes:
        is_supportable: True only when all four required kinds of evidence are present
            and usable. False for any other reason at all — a recommendation built on an
            incomplete set is not one anyone should trust, so this is deliberately an
            all-or-nothing reading rather than a percentage (FR-1.6).
        missing_or_unusable: The kinds of evidence the merchant can still fix, in the
            fixed reporting order — never includes anything unreadable, since that is not
            the merchant's gap to close.
        requests: One specific, ready-to-send sentence per kind in `missing_or_unusable`.
            Named exactly, such as "a photograph of the outer box", never "more evidence".
        unreadable: The kinds of evidence we could not read ourselves, in the fixed
            reporting order. Any entry here means a person has to look at this claim
            regardless of how good everything else is (NFR-4).
        needs_escalation: True whenever `unreadable` is not empty. Kept as its own field
            rather than asking a caller to check `unreadable` for emptiness, since missing
            this check is exactly how a merchant would end up asked to fix our mistake.
        reason: One or two plain sentences summarising the verdict for a representative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_supportable: bool
    missing_or_unusable: tuple[EvidenceKind, ...] = ()
    requests: tuple[str, ...] = ()
    unreadable: tuple[EvidenceKind, ...] = ()
    needs_escalation: bool = False
    reason: str


def assess_evidence_sufficiency(findings: Sequence[EvidenceFinding]) -> SufficiencyAssessment:
    """Read what was found for each kind of evidence, and say what a rep should do about it.

    This adds no new judgement about any single piece of evidence — `evidence.py` already
    decided whether each one is present, missing, unusable, or unreadable. It only
    assembles those decisions into a verdict: can a recommendation stand on this evidence,
    and if not, exactly what should happen next for each gap.

    Args:
        findings: What was found for each of the four required kinds, in any order. A
            kind entirely absent from this sequence — CASE-1005's zero attachments, for
            instance — counts as missing, the same as `evidence.py`'s own helpers already
            treat it; an empty sequence is a real claim, not a caller's mistake.

    Returns:
        Whether the evidence supports a recommendation, exactly what to ask the merchant
        for where they can still help, and which kinds need a person instead because the
        gap is on our side.
    """
    indexed = findings_by_kind(findings)
    to_ask = gaps_the_merchant_can_fill(findings)
    unreadable = gaps_we_caused(findings)

    requests = tuple(_request_for(kind, indexed.get(kind)) for kind in to_ask)

    return SufficiencyAssessment(
        is_supportable=all_present(findings),
        missing_or_unusable=to_ask,
        requests=requests,
        unreadable=unreadable,
        needs_escalation=bool(unreadable),
        reason=_reason_for(findings, to_ask, unreadable),
    )


def _request_for(kind: EvidenceKind, finding: EvidenceFinding | None) -> str:
    """One sentence asking the merchant for exactly the thing that is missing or unusable.

    Named specifically rather than as "more evidence", so a rep can send this straight to
    a merchant. When something was sent but could not be relied on, the sentence names
    what was wrong with it, quoting the reason already recorded against that finding
    rather than inventing a fresh one.
    """
    noun = _ASK_FOR[kind]
    if finding is not None and finding.state is EvidenceState.UNUSABLE:
        problem = finding.problem or "could not be relied on"
        return f"Ask the merchant to send {noun} again — what they sent was {problem}."
    return f"Ask the merchant for {noun}."


def _reason_for(
    findings: Sequence[EvidenceFinding],
    to_ask: tuple[EvidenceKind, ...],
    unreadable: tuple[EvidenceKind, ...],
) -> str:
    """One or two plain sentences summarising the verdict, for a rep who reads nothing else."""
    if not to_ask and not unreadable:
        return (
            "All four required pieces of evidence are present and usable, so a "
            "recommendation is supportable."
        )

    sentences: list[str] = []
    if unreadable:
        labels = _and_list([_LABEL[kind] for kind in unreadable])
        # "could", not "is"/"are": the modal verb does not change for a singular or a
        # plural subject, so there is no agreement to get wrong here.
        sentences.append(
            f"{labels} could not be read on our side, so this claim needs a person "
            "regardless of anything else here."
        )
    if to_ask:
        if not findings:
            sentences.append(
                "Nothing has been sent for any of the four required kinds of evidence, "
                "so ask the merchant for all four before recommending anything."
            )
        else:
            labels = _and_list([_LABEL[kind] for kind in to_ask])
            verb = "is" if len(to_ask) == 1 else "are"
            sentences.append(
                f"{labels} {verb} missing or unusable, so no recommendation can be made "
                "until the merchant sends them."
            )
    return " ".join(sentences)


def _and_list(parts: Sequence[str]) -> str:
    """Join phrases the way a sentence would, so a reason reads as English."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
