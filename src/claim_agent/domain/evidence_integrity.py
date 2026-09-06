from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Attachment, BlankToNone, Case, UtcDatetime


class DuplicateEvidenceBasis(StrEnum):
    """How two attachments were established to be the same file."""

    STORAGE_KEY = "storage_key"
    FINGERPRINT = "fingerprint"
    BOTH = "both"


class DuplicateEvidenceGroup(BaseModel):
    """One photograph that appears more than once among the attachments looked at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    basis: DuplicateEvidenceBasis
    detail: str


class DuplicateEvidenceReport(BaseModel):
    """Every duplicate photograph found among a set of attachments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    within_claim_groups: tuple[DuplicateEvidenceGroup, ...] = ()
    cross_claim_groups: tuple[DuplicateEvidenceGroup, ...] = ()

    @property
    def has_duplicates(self) -> bool:
        """True when at least one photograph turned up more than once."""
        return bool(self.within_claim_groups or self.cross_claim_groups)


def fingerprint(data: bytes) -> str:
    """Take a byte-exact fingerprint of a file, so two downloads can be compared."""
    return hashlib.sha256(data).hexdigest()


def storage_key(url: str) -> str:
    """The stable part of a signed storage URL — everything except its signature."""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def find_duplicate_evidence(
    attachments: Sequence[Attachment],
    claim_id_by_attachment: Mapping[str, str],
    *,
    fingerprints_by_id: Mapping[str, str] | None = None,
) -> DuplicateEvidenceReport:
    """Find every photograph that shows up more than once among these attachments."""
    fingerprints = fingerprints_by_id or {}
    _require_claim_ids(attachments, claim_id_by_attachment)

    by_storage_key: dict[str, list[Attachment]] = {}
    for attachment in attachments:
        by_storage_key.setdefault(storage_key(attachment.url), []).append(attachment)

    by_fingerprint: dict[str, list[Attachment]] = {}
    for attachment in attachments:
        digest = fingerprints.get(attachment.attachment_id)
        if digest is not None:
            by_fingerprint.setdefault(digest, []).append(attachment)

    clusters: list[tuple[list[Attachment], DuplicateEvidenceBasis]] = []
    seen_membership: dict[frozenset[str], int] = {}

    def add_cluster(members: list[Attachment], basis: DuplicateEvidenceBasis) -> None:
        membership = frozenset(one.attachment_id for one in members)
        existing_index = seen_membership.get(membership)
        if existing_index is not None:
            existing_members, existing_basis = clusters[existing_index]
            if existing_basis is not basis:
                clusters[existing_index] = (existing_members, DuplicateEvidenceBasis.BOTH)
            return
        seen_membership[membership] = len(clusters)
        clusters.append((members, basis))

    for members in by_storage_key.values():
        if len(members) > 1:
            add_cluster(members, DuplicateEvidenceBasis.STORAGE_KEY)
    for members in by_fingerprint.values():
        if len(members) > 1:
            add_cluster(members, DuplicateEvidenceBasis.FINGERPRINT)

    within_claim: list[DuplicateEvidenceGroup] = []
    cross_claim: list[DuplicateEvidenceGroup] = []
    for members, basis in clusters:
        claim_ids = _unique_in_order(claim_id_by_attachment[one.attachment_id] for one in members)
        group = DuplicateEvidenceGroup(
            attachment_ids=tuple(one.attachment_id for one in members),
            claim_ids=claim_ids,
            basis=basis,
            detail=_duplicate_detail(members, claim_ids, basis),
        )
        (within_claim if len(claim_ids) <= 1 else cross_claim).append(group)

    return DuplicateEvidenceReport(
        within_claim_groups=tuple(within_claim), cross_claim_groups=tuple(cross_claim)
    )


def _require_claim_ids(
    attachments: Sequence[Attachment], claim_id_by_attachment: Mapping[str, str]
) -> None:
    """Refuse to guess which claim an attachment came from."""
    missing = [
        attachment.attachment_id
        for attachment in attachments
        if attachment.attachment_id not in claim_id_by_attachment
    ]
    if missing:
        raise ValueError(
            "claim_id_by_attachment has no entry for attachment id(s): " + ", ".join(missing)
        )


def _duplicate_detail(
    members: Sequence[Attachment], claim_ids: tuple[str, ...], basis: DuplicateEvidenceBasis
) -> str:
    """Write one plain sentence describing a duplicate finding."""
    names = _and_list([_label(attachment) for attachment in members])
    reason = {
        DuplicateEvidenceBasis.STORAGE_KEY: "they point at the same stored file",
        DuplicateEvidenceBasis.FINGERPRINT: "their downloaded bytes are identical",
        DuplicateEvidenceBasis.BOTH: (
            "they point at the same stored file and their downloaded bytes are identical"
        ),
    }[basis]
    if len(claim_ids) <= 1:
        return f"{names} are the same photograph, both on {claim_ids[0]} — {reason}."
    claims = _and_list(list(claim_ids))
    return f"{names} are the same photograph, uploaded to different claims ({claims}) — {reason}."


def _label(attachment: Attachment) -> str:
    """The name to show for an attachment: its file name where one was given."""
    return attachment.file_name or attachment.attachment_id


class CaseSummary(BaseModel):
    """One row of ShipBob's case listing (`GET /cases`) — not the full case record."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str
    case_number: BlankToNone = None
    status: BlankToNone = None
    subject: BlankToNone = None
    created_date: UtcDatetime


class RelationSignal(StrEnum):
    """One way two claims can turn out to be connected, strongest first."""

    SAME_SHIPMENT = "same_shipment"
    SAME_ORDER = "same_order"
    SAME_USER = "same_user"
    SAME_ACCOUNT_NAME = "same_account_name"


class RelatedClaim(BaseModel):
    """One other claim connected to the claim being looked at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    shared_signals: tuple[RelationSignal, ...]
    strongest_signal: RelationSignal
    detail: str


class RelatedClaims(BaseModel):
    """Every other claim connected to one claim, and what connects them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    related: tuple[RelatedClaim, ...] = ()

    @property
    def has_related_claims(self) -> bool:
        """True when at least one other claim shares something with this one."""
        return bool(self.related)


_SIGNAL_LABELS: dict[RelationSignal, str] = {
    RelationSignal.SAME_SHIPMENT: "the same shipment",
    RelationSignal.SAME_ORDER: "the same order",
    RelationSignal.SAME_USER: "the same merchant account",
    RelationSignal.SAME_ACCOUNT_NAME: "the same merchant name",
}


def find_related_claims(case: Case, others: Sequence[Case]) -> RelatedClaims:
    """Find every other claim connected to this one by shipment, order or merchant."""
    related: list[RelatedClaim] = []
    for other in others:
        if other.case_id == case.case_id:
            continue
        signals = _shared_signals(case, other)
        if not signals:
            continue
        related.append(
            RelatedClaim(
                case_id=other.case_id,
                shared_signals=signals,
                strongest_signal=signals[0],
                detail=_relation_detail(other, signals),
            )
        )
    return RelatedClaims(case_id=case.case_id, related=tuple(related))


def _shared_signals(case: Case, other: Case) -> tuple[RelationSignal, ...]:
    """Every signal two claims share, strongest first. Never guesses past a `None`."""
    signals: list[RelationSignal] = []
    if _shared(case.shipment_id, other.shipment_id):
        signals.append(RelationSignal.SAME_SHIPMENT)
    if _shared(case.order_id, other.order_id):
        signals.append(RelationSignal.SAME_ORDER)
    if _shared(case.user_id, other.user_id):
        signals.append(RelationSignal.SAME_USER)
    if _shared(case.account_name, other.account_name):
        signals.append(RelationSignal.SAME_ACCOUNT_NAME)
    return tuple(signals)


def _shared(a: str | None, b: str | None) -> bool:
    """Two values count as shared only when both are present and identical."""
    return a is not None and b is not None and a == b


def _relation_value(other: Case, signal: RelationSignal) -> str | None:
    """The actual id or name that made a given signal match, for the detail sentence."""
    return {
        RelationSignal.SAME_SHIPMENT: other.shipment_id,
        RelationSignal.SAME_ORDER: other.order_id,
        RelationSignal.SAME_USER: other.user_id,
        RelationSignal.SAME_ACCOUNT_NAME: other.account_name,
    }[signal]


def _relation_detail(other: Case, signals: tuple[RelationSignal, ...]) -> str:
    """Write one plain sentence naming what two claims share."""
    parts = [f"{_SIGNAL_LABELS[signal]} ({_relation_value(other, signal)})" for signal in signals]
    return f"{other.case_id} shares {_and_list(parts)} with this claim."


def _unique_in_order(values: Iterable[str]) -> tuple[str, ...]:
    """The values, each kept once, in the order they first appeared."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return tuple(seen)


def _and_list(parts: Sequence[str]) -> str:
    """Join phrases the way a sentence would, so a detail line reads as English."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
