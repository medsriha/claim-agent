from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceKind(StrEnum):
    """The four pieces of evidence a reimbursement decision needs."""

    INVOICE = "invoice"
    CUSTOMER_CONFIRMATION = "customer_confirmation"
    DAMAGED_PRODUCT_PHOTO = "damaged_product_photo"
    OUTER_PACKAGING_PHOTO = "outer_packaging_photo"


REQUIRED_EVIDENCE: tuple[EvidenceKind, ...] = (
    EvidenceKind.INVOICE,
    EvidenceKind.CUSTOMER_CONFIRMATION,
    EvidenceKind.DAMAGED_PRODUCT_PHOTO,
    EvidenceKind.OUTER_PACKAGING_PHOTO,
)
"""All four kinds, in the order the requirements list them."""

SHARED_EVIDENCE: tuple[EvidenceKind, ...] = (
    EvidenceKind.INVOICE,
    EvidenceKind.CUSTOMER_CONFIRMATION,
    EvidenceKind.OUTER_PACKAGING_PHOTO,
)
"""The three kinds that describe the shipment rather than any one product."""


class EvidenceState(StrEnum):
    """Whether a piece of evidence can be relied on, and whose problem it is if not."""

    PRESENT = "present"
    MISSING = "missing"
    UNUSABLE = "unusable"
    UNREADABLE = "unreadable"


class EvidenceFinding(BaseModel):
    """What was found for one of the four pieces of evidence, and where."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: EvidenceKind
    state: EvidenceState
    observed: str
    attachment_id: str | None = None
    problem: str | None = None

    @property
    def is_satisfied(self) -> bool:
        """True only when this piece of evidence can actually be relied on."""
        return self.state is EvidenceState.PRESENT


def findings_by_kind(
    findings: Sequence[EvidenceFinding],
) -> dict[EvidenceKind, EvidenceFinding]:
    """Index findings by which piece of evidence they are about."""
    return {finding.kind: finding for finding in findings}


def all_present(findings: Sequence[EvidenceFinding]) -> bool:
    """True when all four pieces of evidence are there and usable."""
    indexed = findings_by_kind(findings)
    return all(kind in indexed and indexed[kind].is_satisfied for kind in REQUIRED_EVIDENCE)


def gaps_the_merchant_can_fill(
    findings: Sequence[EvidenceFinding],
) -> tuple[EvidenceKind, ...]:
    """The pieces of evidence to ask the merchant for, in the fixed reporting order."""
    indexed = findings_by_kind(findings)
    return tuple(
        kind
        for kind in REQUIRED_EVIDENCE
        if kind not in indexed
        or indexed[kind].state in (EvidenceState.MISSING, EvidenceState.UNUSABLE)
    )


def gaps_we_caused(findings: Sequence[EvidenceFinding]) -> tuple[EvidenceKind, ...]:
    """The pieces of evidence we could not read ourselves, in the reporting order."""
    indexed = findings_by_kind(findings)
    return tuple(
        kind
        for kind in REQUIRED_EVIDENCE
        if kind in indexed and indexed[kind].state is EvidenceState.UNREADABLE
    )
