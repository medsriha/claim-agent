from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceKind(StrEnum):
    """The four pieces of evidence a reimbursement decision needs.

    `INVOICE` is proof of what was ordered and what it cost. `CUSTOMER_CONFIRMATION`
    is the end customer telling the merchant the parcel arrived damaged, usually as
    a screenshot of an email. `DAMAGED_PRODUCT_PHOTO` shows the broken product
    itself and is the one item settled per claim line rather than per claim.
    `OUTER_PACKAGING_PHOTO` shows the box the order arrived in — it has to have been
    photographed, not to be damaged, because an intact box with a broken product
    inside is a perfectly legitimate claim (FR-1.11).
    """

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
"""All four kinds, in the order the requirements list them.

Every report shows all four, present or not, so a rep sees what was found rather
than inferring it from silence — and always in this order, so two reports read the
same way (FR-2.2).
"""

SHARED_EVIDENCE: tuple[EvidenceKind, ...] = (
    EvidenceKind.INVOICE,
    EvidenceKind.CUSTOMER_CONFIRMATION,
    EvidenceKind.OUTER_PACKAGING_PHOTO,
)
"""The three kinds that describe the shipment rather than any one product.

Settled once for the whole claim and handed to every claim line (FR-1a.3). That is
partly a cost control — the invoice is not re-read once per product — and mostly a
consistency guarantee: two products in one claim can never disagree about whether
the outer box was photographed.
"""


class EvidenceState(StrEnum):
    """Whether a piece of evidence can be relied on, and whose problem it is if not.

    `PRESENT` means it is there and good enough to draw a conclusion from.

    `MISSING` means no such attachment was sent.

    `UNUSABLE` means one was sent but cannot support a conclusion — too blurry, too
    dark, too cropped, the wrong subject. The merchant can fix this, and the reason
    is recorded so they can be asked for something specific (FR-1.5, FR-1.7).

    `UNREADABLE` means **we** could not fetch or analyse the image. The merchant
    can do nothing about it and must not be asked to. This goes to a person
    (NFR-4).
    """

    PRESENT = "present"
    MISSING = "missing"
    UNUSABLE = "unusable"
    UNREADABLE = "unreadable"


class EvidenceFinding(BaseModel):
    """What was found for one of the four pieces of evidence, and where.

    `attachment_id` names the exact image this finding came from, so a rep can look
    at the same photograph the system looked at (FR-2.2). It is `None` when the
    evidence is missing, because there is no image to point at.

    `observed` is one plain sentence saying what was actually seen. `problem` says
    why the evidence cannot be relied on and is set only for `UNUSABLE` and
    `UNREADABLE` — for the first it is something the merchant can act on, for the
    second it is a fault on our side.
    """

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
    """Index findings by which piece of evidence they are about.

    Later findings win where a kind appears twice, which is how a claim line's own
    look at the damage photographs replaces whatever the claim-level pass recorded
    for that kind.
    """
    return {finding.kind: finding for finding in findings}


def all_present(findings: Sequence[EvidenceFinding]) -> bool:
    """True when all four pieces of evidence are there and usable.

    Anything short of all four means no reimbursement can be recommended: the
    system asks and waits rather than approving partially (FR-1.6). A finding
    absent from the sequence altogether counts as not satisfied, so an incomplete
    set can never read as a complete one.
    """
    indexed = findings_by_kind(findings)
    return all(kind in indexed and indexed[kind].is_satisfied for kind in REQUIRED_EVIDENCE)


def gaps_the_merchant_can_fill(
    findings: Sequence[EvidenceFinding],
) -> tuple[EvidenceKind, ...]:
    """The pieces of evidence to ask the merchant for, in the fixed reporting order.

    Covers evidence that is missing and evidence that arrived unusable — both are
    things the merchant can send again. A kind not mentioned in the findings at all
    counts as missing, because a piece of evidence nobody looked for is not a piece
    of evidence we have.

    Deliberately excludes anything `UNREADABLE`: that is our failure, and a request
    the merchant cannot act on is worse than no request (FR-1.7).
    """
    indexed = findings_by_kind(findings)
    return tuple(
        kind
        for kind in REQUIRED_EVIDENCE
        if kind not in indexed
        or indexed[kind].state in (EvidenceState.MISSING, EvidenceState.UNUSABLE)
    )


def gaps_we_caused(findings: Sequence[EvidenceFinding]) -> tuple[EvidenceKind, ...]:
    """The pieces of evidence we could not read ourselves, in the reporting order.

    Any of these means the claim goes to a person rather than back to the merchant,
    however good the rest of the evidence is (NFR-4).
    """
    indexed = findings_by_kind(findings)
    return tuple(
        kind
        for kind in REQUIRED_EVIDENCE
        if kind in indexed and indexed[kind].state is EvidenceState.UNREADABLE
    )
