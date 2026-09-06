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
"""What to ask the merchant for, per kind of evidence — specific enough to send as-is."""

_LABEL: dict[EvidenceKind, str] = {
    EvidenceKind.INVOICE: "the invoice",
    EvidenceKind.CUSTOMER_CONFIRMATION: "the customer's confirmation that it arrived damaged",
    EvidenceKind.DAMAGED_PRODUCT_PHOTO: "a photograph of the damaged product",
    EvidenceKind.OUTER_PACKAGING_PHOTO: "a photograph of the outer box",
}
"""Short names for each kind of evidence, for the one-sentence summary rather than the"""


class SufficiencyAssessment(BaseModel):
    """Whether the evidence gathered so far can support a recommendation, and what to do next."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_supportable: bool
    missing_or_unusable: tuple[EvidenceKind, ...] = ()
    requests: tuple[str, ...] = ()
    unreadable: tuple[EvidenceKind, ...] = ()
    needs_rep_clarification: bool = False
    reason: str


def assess_evidence_sufficiency(findings: Sequence[EvidenceFinding]) -> SufficiencyAssessment:
    """Read what was found for each kind of evidence, and say what a rep should do about it."""
    indexed = findings_by_kind(findings)
    to_ask = gaps_the_merchant_can_fill(findings)
    unreadable = gaps_we_caused(findings)

    requests = tuple(_request_for(kind, indexed.get(kind)) for kind in to_ask)

    return SufficiencyAssessment(
        is_supportable=all_present(findings),
        missing_or_unusable=to_ask,
        requests=requests,
        unreadable=unreadable,
        needs_rep_clarification=bool(unreadable),
        reason=_reason_for(findings, to_ask, unreadable),
    )


def _request_for(kind: EvidenceKind, finding: EvidenceFinding | None) -> str:
    """One sentence asking the merchant for exactly the thing that is missing or unusable."""
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
