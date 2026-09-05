"""Whether the evidence on a claim can be trusted at face value.

Two questions, and this module answers both without reaching a verdict on either:

1. **Has this exact photograph shown up before?** A merchant sometimes attaches the
   same picture twice by mistake. Rarer, and worth a person's attention: the same
   picture turns up on *two different merchants' claims*. That is real, not a
   hypothetical worry — `CASE-1001`'s fourth attachment, `kgray4.jpeg`, and
   `CASE-1002`'s `IMG_9722.jpeg` resolve to the identical storage location, and the
   downloaded bytes are identical too. Two different merchants, two different
   support cases, one photograph.
2. **Is this claim connected to another one already in the system?** The same
   shipment, the same order, or the same merchant showing up on more than one case
   is a fact worth a person seeing before they decide anything.

**Neither answer is a decision.** A duplicate photograph is not proof of fraud — a
merchant legitimately re-sends a picture that did not attach the first time, and a
support tool that shouted "fraud" every time that happened would train reps to
ignore it. A shared shipment is not proof of anything either; it might mean two
merchants are innocently reporting the same event. This module's job stops at
"here is what matches, and here is why it might matter" (FR-1.13: the system does
not narrow an ambiguous finding down to one answer, and a duplicate or a
connection is exactly that kind of finding).

**No requirement covers this.** REQUIREMENTS.md does not mention duplicate
attachments or related claims at all; both were found by reading the mock API's
actual sample data, not by anything specified. The nearest ideas already in the
requirements are FR-1.13 (never narrow an ambiguous match to one answer), FR-0.6
and NFR-1 (the same input must produce the same output every time), and NFR-4
(an uncertain finding goes to a person, not into a silent decision). Everything
here is invented from those principles; DESIGN.md records it as such.

Nothing here reaches out to anything. Comparing bytes for a "fingerprint" needs
the bytes themselves, and downloading them is somebody else's job — this module
only ever compares hashes and identifiers it is handed. That keeps it fast,
testable without a network, and exactly repeatable on the same input (FR-0.6).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Attachment, BlankToNone, Case, UtcDatetime

# ---------------------------------------------------------------------------
# Part A — the same photograph, more than once
# ---------------------------------------------------------------------------


class DuplicateEvidenceBasis(StrEnum):
    """How two attachments were established to be the same file.

    `STORAGE_KEY` means their URLs point at the same stored file — established
    without downloading anything, and so tried first. `FINGERPRINT` means their
    downloaded bytes hashed identically, which is stronger evidence but only
    available when a caller has already fetched and hashed both files. `BOTH`
    means the two agreed: the cheap check and the expensive check found the same
    pair.
    """

    STORAGE_KEY = "storage_key"
    FINGERPRINT = "fingerprint"
    BOTH = "both"


class DuplicateEvidenceGroup(BaseModel):
    """One photograph that appears more than once among the attachments looked at.

    Attributes:
        attachment_ids: every attachment that is this same file, in the order they
            were encountered.
        claim_ids: every claim these attachments were filed under, in the order
            first seen. Length one means one merchant sent the same picture twice
            on their own claim. Length more than one means the same picture is on
            two different merchants' claims — the more serious finding, and the
            reason `find_duplicate_evidence` reports the two kinds separately
            rather than folding them into one list.
        basis: how the match was established.
        detail: one plain sentence naming the attachments and claims involved,
            ready to show a representative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    basis: DuplicateEvidenceBasis
    detail: str


class DuplicateEvidenceReport(BaseModel):
    """Every duplicate photograph found among a set of attachments.

    **A duplicate here is a fact, not a finding of fraud.** A merchant re-sending a
    photo that failed to attach the first time produces exactly the same signal as
    a photo used to support two unrelated claims; this report cannot and does not
    try to tell those apart. It is a thing a representative should see and weigh,
    the same way FR-1.13 already refuses to pick a winner between two ambiguous
    matches elsewhere in this system.

    Attributes:
        within_claim_groups: duplicate photographs where every copy was filed
            under the same claim — most often an accidental double upload.
        cross_claim_groups: duplicate photographs that span more than one claim —
            the same picture used on two different merchants' cases. Worth more
            scrutiny than the within-claim kind, which is why it is kept apart
            rather than mixed into one list a reader has to filter themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    within_claim_groups: tuple[DuplicateEvidenceGroup, ...] = ()
    cross_claim_groups: tuple[DuplicateEvidenceGroup, ...] = ()

    @property
    def has_duplicates(self) -> bool:
        """True when at least one photograph turned up more than once."""
        return bool(self.within_claim_groups or self.cross_claim_groups)


def fingerprint(data: bytes) -> str:
    """Take a byte-exact fingerprint of a file, so two downloads can be compared.

    Returns the sha256 hex digest of `data`. Two files with the same fingerprint
    are the same bytes, full stop.

    **What this does not catch.** A photograph re-saved by a phone's camera roll,
    recompressed by a messaging app, or cropped by a single pixel produces
    completely different bytes and therefore a completely different fingerprint,
    even though a person looking at both would call them the same picture. Telling
    those apart needs a *perceptual* hash — one that scores images by how alike
    they look rather than by whether their bytes match — and that is a real
    library dependency this project has not taken on for a demo. The cost of
    skipping it: a merchant (or someone reusing a photograph across two claims)
    who re-exports the same picture before re-uploading it defeats this check
    completely, and nothing here will notice. `find_duplicate_evidence` only ever
    catches the exact-copy case.
    """
    return hashlib.sha256(data).hexdigest()


def storage_key(url: str) -> str:
    """The stable part of a signed storage URL — everything except its signature.

    ShipBob's attachment URLs point at blob storage and carry a signed query
    string (`?se=...&sp=r&sv=...&sr=b&sig=...`). That signature is minted per
    request, not stored with the file, so the same picture fetched twice can
    arrive with two different query strings attached to the very same file.
    Comparing whole URLs would call those two requests different files; this
    strips the query string (and anything after it) and keeps the scheme, host
    and path — the part that actually names where the file lives.

    Two attachments with the same storage key are the same file, and knowing
    that costs nothing: no download, no network call. That is why
    `find_duplicate_evidence` tries this before it ever looks at a fingerprint.
    """
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def find_duplicate_evidence(
    attachments: Sequence[Attachment],
    claim_id_by_attachment: Mapping[str, str],
    *,
    fingerprints_by_id: Mapping[str, str] | None = None,
) -> DuplicateEvidenceReport:
    """Find every photograph that shows up more than once among these attachments.

    Two checks run, in order of how much they cost:

    1. **Storage key.** Any attachments whose URLs share a `storage_key` are the
       same file. This needs nothing but the URLs already on hand.
    2. **Fingerprint.** For attachments whose bytes the caller has already
       downloaded and hashed with `fingerprint`, any that share a hash are the
       same file too — catching a copy stored at a genuinely different path that
       the storage-key check alone would miss.

    A pair caught by both checks is not reported twice: it comes back once, with
    `basis` set to `BOTH`.

    Every attachment must have an entry in `claim_id_by_attachment` mapping its
    `attachment_id` to the claim (support case) it came from — this module has no
    other way to know which attachments belong to the same claim and which do
    not, and inventing that field on `Attachment` was ruled out so as not to
    touch a shape other code already depends on.

    Args:
        attachments: every attachment to compare, from however many claims. May
            span one claim (checking for an accidental double upload) or several
            (checking whether a photograph has been reused across claims).
        claim_id_by_attachment: which claim each attachment's `attachment_id`
            came from.
        fingerprints_by_id: sha256 hex digests (from `fingerprint`) the caller
            has already computed, keyed by `attachment_id`. Omit entirely, or
            leave an attachment out of it, to run the storage-key check alone for
            that attachment — an ordinary and cheaper outcome, not a failure.

    Returns:
        Every duplicate found, split into groups confined to one claim and
        groups that cross claims. An input with no duplicates, or an empty list
        of attachments, comes back with both lists empty — that is the normal
        case, not an error (FR-0.6: the same attachments always produce the same
        report).

    Raises:
        ValueError: an attachment's id has no entry in `claim_id_by_attachment`.
            That is a caller wiring mistake, not an ambiguous finding about the
            evidence, so it is refused rather than guessed at.
    """
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
    """Refuse to guess which claim an attachment came from.

    A missing entry here is not an ambiguous fact about the evidence — it means
    the caller never told this function something it needed, so it is reported
    as a mistake rather than silently skipped or grouped under a made-up claim id.
    """
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


# ---------------------------------------------------------------------------
# Part B — claims connected to this one
# ---------------------------------------------------------------------------


class CaseSummary(BaseModel):
    """One row of ShipBob's case listing (`GET /cases`) — not the full case record.

    This is deliberately thin, because that is all the endpoint gives back: an
    id, a case number, a status, a subject line, and when it was filed. It carries
    no `order_id`, `shipment_id`, `user_id` or `account_name` — nothing this
    system uses to tell whether one claim is connected to another. Turning a list
    of these into anything `find_related_claims` can use means reading each case
    in full, one at a time (no requirement covers this; see DESIGN.md).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str
    case_number: BlankToNone = None
    status: BlankToNone = None
    subject: BlankToNone = None
    created_date: UtcDatetime


class RelationSignal(StrEnum):
    """One way two claims can turn out to be connected, strongest first.

    The order matters and is not arbitrary:

    - `SAME_SHIPMENT` is the strongest signal there is. Two claims about the same
      parcel are nearly always the same event reported twice — by the merchant a
      second time, or by two people at the same merchant — rather than two
      genuinely separate problems.
    - `SAME_ORDER` is close behind it. An order can ship in more than one parcel,
      so two claims on the same order are not guaranteed to be about the same
      shipment, but they are still about the very same purchase.
    - `SAME_USER` — the same merchant account filing more than one claim — is
      ordinary business. Merchants ship a lot of parcels, and more than one of
      them arriving damaged is unremarkable on its own.
    - `SAME_ACCOUNT_NAME` is the weakest of the four. It is display text rather
      than a stable identifier — the same text one merchant used before, but
      names can change and are not guaranteed unique the way an id is — so it
      matters most when the merchant id is missing rather than as a replacement
      for `SAME_USER`.
    """

    SAME_SHIPMENT = "same_shipment"
    SAME_ORDER = "same_order"
    SAME_USER = "same_user"
    SAME_ACCOUNT_NAME = "same_account_name"


class RelatedClaim(BaseModel):
    """One other claim connected to the claim being looked at.

    Attributes:
        case_id: the other claim's case id.
        shared_signals: every kind of match found against it, strongest first.
        strongest_signal: the first entry of `shared_signals`, named separately
            so a caller does not have to know the strength ordering itself.
        detail: one plain sentence naming what is shared, ready to show a
            representative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    shared_signals: tuple[RelationSignal, ...]
    strongest_signal: RelationSignal
    detail: str


class RelatedClaims(BaseModel):
    """Every other claim connected to one claim, and what connects them.

    **This reports connections, never a verdict.** Two claims sharing a shipment
    is a strong hint, not a conclusion — deciding what it means is a
    representative's judgement, not this function's (FR-1.13's principle applied
    here: an ambiguous or suggestive finding is reported, never resolved for the
    reader).

    Attributes:
        case_id: the claim these connections were found for.
        related: every other claim that shares at least one signal with it, in
            the order they were checked. Empty means nothing connected — the
            ordinary case for most claims, and not a sign anything went wrong.
    """

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
    """Find every other claim connected to this one by shipment, order or merchant.

    **This takes full case records and does no reading of its own** — a
    deliberate limit, and an honest one. `GET /cases` only ever returns the thin
    summary shape `CaseSummary` holds: no `order_id`, `shipment_id`, `user_id` or
    `account_name`. Relating claims properly therefore means fetching every
    candidate case in full first — one request per case, N+1 requests for N
    candidates — and that cost belongs to whoever calls this, not to a function
    that is supposed to run with no network at all (FR-0.6).

    Args:
        case: the claim to find connections for.
        others: every other claim to check it against, already read in full. A
            case sharing `case.case_id` is skipped rather than reported as
            connected to itself.

    Returns:
        Every other claim that shares at least one signal, each carrying every
        signal it shares and which one to weigh most (see `RelationSignal`).
        Nothing shared at all is the ordinary outcome and comes back as an empty
        `related` list, not an error.
    """
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
    """Two values count as shared only when both are present and identical.

    A claim with no shipment id and another claim with no shipment id are not
    "the same shipment" — they are two claims that are each missing one. Treating
    absence as a match would connect every incomplete claim to every other one.
    """
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


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _unique_in_order(values: Iterable[str]) -> tuple[str, ...]:
    """The values, each kept once, in the order they first appeared.

    A plain dictionary rather than a set: a set's iteration order is not
    guaranteed to be the same between two runs of the same program, and the
    order these come back in ends up in a report a representative reads, which
    has to be the same twice for the same input (FR-0.6, NFR-1).
    """
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
