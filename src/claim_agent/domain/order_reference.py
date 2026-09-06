from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from claim_agent.policy import Policy

MAX_TEXT_SCANNED: Final = 20_000
"""How much evidence text is scanned for references."""

MIN_REFERENCE_LENGTH: Final = 5
"""How long a run of characters must be before it is treated as a reference at all."""

_REFERENCE_PATTERN: Final = re.compile(r"#?\b([A-Za-z]{0,4}[-_]?\d{3,}[A-Za-z0-9-]*)\b")
"""Something that looks like an order or shipment reference."""

_TRIM_PATTERN: Final = re.compile(r"[^a-z0-9]")
"""What is removed before two references are compared: everything but letters and digits."""


class ReferenceShape(StrEnum):
    """What a reference looked like, which hints at whose numbering it is."""

    DIGITS = "digits"
    PREFIXED = "prefixed"
    FULFILMENT = "fulfilment"


class MatchStrength(StrEnum):
    """How firmly a reference ties to one of this claim's identifiers, strongest first."""

    EXACT = "exact"
    NORMALISED = "normalised"
    CONTAINED = "contained"
    NONE = "none"


_SCORES: Final = {
    MatchStrength.EXACT: 1.0,
    MatchStrength.NORMALISED: 0.9,
    MatchStrength.CONTAINED: 0.65,
    MatchStrength.NONE: 0.0,
}
"""What each kind of match is worth, from 0 to 1."""


class ExtractedReference(BaseModel):
    """One thing in evidence text that looks like an order or shipment reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    normalised: str
    shape: ReferenceShape


class ReferenceMatch(BaseModel):
    """One reference weighed against one of this claim's identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: ExtractedReference
    matched_field: str
    matched_value: str
    strength: MatchStrength
    score: float
    explanation: str


class ReferenceResolution(BaseModel):
    """Whether a document can be shown to belong to this claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    belongs_to_claim: bool = False
    best: ReferenceMatch | None = None
    is_ambiguous: bool = False
    candidates: tuple[ReferenceMatch, ...] = ()
    references_found: tuple[ExtractedReference, ...] = ()
    expected: tuple[str, ...] = ()
    reason: str


def extract_references(text: str) -> tuple[ExtractedReference, ...]:
    """Pull everything out of evidence text that looks like an order or shipment reference."""
    found: dict[str, ExtractedReference] = {}
    for match in _REFERENCE_PATTERN.finditer(text[:MAX_TEXT_SCANNED]):
        raw = match.group(1)
        normalised = _for_comparison(raw)
        if len(normalised) < MIN_REFERENCE_LENGTH or normalised in found:
            continue
        found[normalised] = ExtractedReference(raw=raw, normalised=normalised, shape=_shape_of(raw))
    return tuple(found.values())


def resolve_reference(
    text: str,
    policy: Policy,
    *,
    order_id: str | None = None,
    shipment_id: str | None = None,
    case_number: str | None = None,
    case_id: str | None = None,
) -> ReferenceResolution:
    """Work out whether a document belongs to this claim, and say how confident that is."""
    expected = [
        ("order_id", order_id),
        ("shipment_id", shipment_id),
        ("case_number", case_number),
        ("case_id", case_id),
    ]
    known = [(field, value) for field, value in expected if value]
    references = extract_references(text)

    if not references or not known:
        return ReferenceResolution(
            references_found=references,
            expected=tuple(value for _, value in known),
            reason=_nothing_to_compare(known),
        )

    candidates = _best_match_per_reference(references, known)
    if not candidates:
        return ReferenceResolution(
            references_found=references,
            expected=tuple(value for _, value in known),
            reason=(
                f"None of the {len(references)} reference(s) on this document relates to any "
                "identifier on this claim. It may belong to a different order."
            ),
        )

    bar = policy.min_order_reference_confidence
    cleared = [one for one in candidates if one.score >= bar]
    top = candidates[0]

    if not cleared:
        return ReferenceResolution(
            candidates=tuple(candidates),
            references_found=references,
            expected=tuple(value for _, value in known),
            reason=(
                f"The closest thing to a match is {top.explanation} That is not firm enough "
                "to treat this document as belonging to this claim."
            ),
        )

    tied = [one for one in cleared if one.score == top.score]
    if len(tied) > 1:
        listed = " and ".join(one.reference.raw for one in tied)
        return ReferenceResolution(
            is_ambiguous=True,
            candidates=tuple(candidates),
            references_found=references,
            expected=tuple(value for _, value in known),
            reason=(
                f"{listed} tie for the best match on this document, so which order it is "
                "for was not decided. Somebody has to say."
            ),
        )

    return ReferenceResolution(
        belongs_to_claim=True,
        best=top,
        candidates=tuple(candidates),
        references_found=references,
        expected=tuple(value for _, value in known),
        reason=f"This document belongs to this claim: {top.explanation}",
    )


def _best_match_per_reference(
    references: Sequence[ExtractedReference], known: Sequence[tuple[str, str]]
) -> list[ReferenceMatch]:
    """The strongest relationship each reference has with any of this claim's identifiers."""
    matches: list[tuple[int, ReferenceMatch]] = []
    for position, reference in enumerate(references):
        best: ReferenceMatch | None = None
        for field, value in known:
            strength = _strength_between(reference, value)
            if strength is MatchStrength.NONE:
                continue
            if best is None or _SCORES[strength] > best.score:
                best = ReferenceMatch(
                    reference=reference,
                    matched_field=field,
                    matched_value=value,
                    strength=strength,
                    score=_SCORES[strength],
                    explanation=_explain(reference, field, value, strength),
                )
        if best is not None:
            matches.append((position, best))
    return [one for _, one in sorted(matches, key=lambda pair: (-pair[1].score, pair[0]))]


def _strength_between(reference: ExtractedReference, value: str) -> MatchStrength:
    """How firmly one reference relates to one identifier."""
    if reference.raw == value:
        return MatchStrength.EXACT
    trimmed = _for_comparison(value)
    if not trimmed or len(trimmed) < MIN_REFERENCE_LENGTH:
        return MatchStrength.NONE
    if reference.normalised == trimmed:
        return MatchStrength.NORMALISED
    if reference.normalised in trimmed or trimmed in reference.normalised:
        return MatchStrength.CONTAINED
    return MatchStrength.NONE


def _explain(reference: ExtractedReference, field: str, value: str, strength: MatchStrength) -> str:
    """Why this reference and this identifier are related, in a sentence a person can check."""
    named = field.replace("_", " ")
    if strength is MatchStrength.EXACT:
        return f"{reference.raw} on the document is this claim's {named} exactly."
    if strength is MatchStrength.NORMALISED:
        return (
            f"{reference.raw} on the document is this claim's {named} {value}, once "
            "capitals and punctuation are ignored."
        )
    return (
        f"{reference.raw} on the document and this claim's {named} {value} contain one "
        "another, so they are probably two writings of the same number — but they are not "
        "the same number."
    )


def _nothing_to_compare(known: Sequence[tuple[str, str]]) -> str:
    """Say which side of the comparison was empty, because they mean different things."""
    if not known:
        return (
            "This claim carries no order, shipment or case number, so there is nothing to "
            "tie a document to."
        )
    return (
        "Nothing on this document looks like an order or shipment reference, so it cannot "
        "be tied to this claim either way."
    )


def _shape_of(raw: str) -> ReferenceShape:
    """What a reference looked like, which hints at whose numbering it belongs to."""
    if "fulfillment" in raw.casefold() or "fulfilment" in raw.casefold():
        return ReferenceShape.FULFILMENT
    return ReferenceShape.DIGITS if raw.isdigit() else ReferenceShape.PREFIXED


def _for_comparison(value: str) -> str:
    """Reduce a reference to the form two of them are compared in."""
    return _TRIM_PATTERN.sub("", value.casefold())
