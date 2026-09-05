"""Proving that a document in a photograph belongs to the claim in front of us.

A merchant attaches a photograph of an invoice. The investigation reads prices off it and
recommends a payout. Nothing anywhere checks that the invoice is for *this* claim.

That is not a hypothetical worry, because order numbers never match across systems in
ShipBob's own sample data. One claim is order `337761802` to ShipBob, `#HS3449170` on the
merchant's support screen, and `Store Order # 344917` on the invoice itself — three
numbers for one order, and **none of them is the ShipBob order id**. Another shows
`#SO387378` with a purchase order of `#329233`, where ShipBob knows it as `336431771`.

So the dangerous case is not a document that fails to match. It is a document that
*silently* fails to match and gets read anyway: reasoning over another customer's invoice
produces a recommendation that is confident, detailed, and about the wrong order.

**No requirement covers this.** It came from comparing the sample claims' records against
the photographs attached to them. The nearest ones are FR-1.13, which forbids narrowing two
possibilities to one, and NFR-4.

**Nothing here decides anything.** It says how strongly a document ties to this claim and
what it found, and a person decides whether that is good enough.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from claim_agent.policy import Policy

MAX_TEXT_SCANNED: Final = 20_000
"""How much evidence text is scanned for references.

Text read off a photograph is untrusted and could be any length. Twenty thousand
characters is far more than any invoice, and stopping there means a huge input costs
bounded time rather than unbounded time.
"""

MIN_REFERENCE_LENGTH: Final = 5
"""How long a run of characters must be before it is treated as a reference at all.

A bare `1` or `24` appears in every document ever printed — quantities, page numbers,
street numbers — and would match something by chance. Five is chosen because the shortest
real identifier in ShipBob's sample data is the six-digit `329233`, so five leaves a
little room without letting ordinary small numbers in. Nothing about it is sacred; it is
here rather than buried in a condition so it can be argued with.
"""

_REFERENCE_PATTERN: Final = re.compile(r"#?\b([A-Za-z]{0,4}[-_]?\d{3,}[A-Za-z0-9-]*)\b")
"""Something that looks like an order or shipment reference.

Deliberately shaped around what the sample data actually contains: a bare run of digits
(`342578703`), a short letter prefix in front of digits (`HS3449170`, `SO387378`), and a
longer hyphenated form (`ShipBobFulfillment-169579`). Anything with no digits at all is
not a reference — it is a word.
"""

_TRIM_PATTERN: Final = re.compile(r"[^a-z0-9]")
"""What is removed before two references are compared: everything but letters and digits."""


class ReferenceShape(StrEnum):
    """What a reference looked like, which hints at whose numbering it is.

    `DIGITS` is ShipBob's own style — their order, shipment and case numbers are all plain
    runs of digits. `PREFIXED` is almost always a merchant's own numbering, as in
    `HS3449170`. `FULFILMENT` is ShipBob's fulfilment id, which names a shipment but is not
    the shipment id.
    """

    DIGITS = "digits"
    PREFIXED = "prefixed"
    FULFILMENT = "fulfilment"


class MatchStrength(StrEnum):
    """How firmly a reference ties to one of this claim's identifiers, strongest first.

    Every one of these is explainable to a representative in a sentence, which matters:
    somebody has to be able to disagree with the reasoning rather than trust a number.
    """

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
"""What each kind of match is worth, from 0 to 1.

**There is no fuzzy string similarity here, deliberately.** An order number is not a word.
"Looks eighty percent like `337761802`" is a meaningless statement about digits, and a
scoring function that produced it would give a confident-looking number to a comparison
that means nothing. Every score below comes from a relationship a person can check by eye:
the same characters, the same characters ignoring punctuation, or one number sitting
inside the other.

`CONTAINED` is scored below the others but still above the default confidence bar, because
it is the real CASE-1003 situation — `344917` printed on an invoice against `3449170` on
the merchant's screen — and treating that as no relation at all would be wrong. It is a
lead, not a proof, and its score says so.
"""


class ExtractedReference(BaseModel):
    """One thing in evidence text that looks like an order or shipment reference.

    Attributes:
        raw: Exactly as it appeared, so a representative can find it on the document.
        normalised: Case-folded with punctuation and any leading `#` removed, which is the
            form two references are compared in.
        shape: What it looked like.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    normalised: str
    shape: ReferenceShape


class ReferenceMatch(BaseModel):
    """One reference weighed against one of this claim's identifiers.

    Attributes:
        reference: What was found on the document.
        matched_field: Which of the claim's identifiers it matched — `order_id`,
            `shipment_id`, `case_number` or `case_id`.
        matched_value: What that identifier actually is.
        strength: How firmly the two are tied.
        score: That strength as a number from 0 to 1.
        explanation: One plain sentence saying why, for somebody who has to agree with it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: ExtractedReference
    matched_field: str
    matched_value: str
    strength: MatchStrength
    score: float
    explanation: str


class ReferenceResolution(BaseModel):
    """Whether a document can be shown to belong to this claim.

    Attributes:
        belongs_to_claim: True only when exactly one match cleared the confidence bar.
            **False is the answer that matters** — it means the document has not been tied
            to this claim, and reading prices off it risks reasoning about somebody else's
            order.
        best: The match that cleared the bar, or `None`.
        is_ambiguous: True when two references tied for the best score. Nothing is chosen
            then, because choosing would be a guess about which document is which (FR-1.13).
        candidates: Every match found, best first, so a person can see what was considered.
        references_found: Everything that looked like a reference, whether it matched or
            not — the raw material, for somebody checking by hand.
        expected: This claim's own identifiers, so a reader can compare without going and
            looking them up.
        reason: One plain sentence a representative can agree or disagree with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    belongs_to_claim: bool = False
    best: ReferenceMatch | None = None
    is_ambiguous: bool = False
    candidates: tuple[ReferenceMatch, ...] = ()
    references_found: tuple[ExtractedReference, ...] = ()
    expected: tuple[str, ...] = ()
    reason: str


def extract_references(text: str) -> tuple[ExtractedReference, ...]:
    """Pull everything out of evidence text that looks like an order or shipment reference.

    Merchant text is untrusted input read off a photograph, so only a bounded amount of it
    is scanned and nothing found in it is allowed to do anything except be compared.

    References come back in the order they appeared, each kept once. Order is preserved
    because a reader compares this against the document by eye, and a list that reorders
    itself between two runs of the same claim reads as a different answer (NFR-1).

    Args:
        text: Whatever was read off the document.

    Returns:
        What was found, possibly nothing. Nothing is an ordinary answer: plenty of
        documents carry no reference we would recognise.
    """
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
    """Work out whether a document belongs to this claim, and say how confident that is.

    Every reference found in the text is weighed against every identifier this claim
    carries, and the best relationship each pair has is kept. The best of those is compared
    against the confidence policy asks for.

    **Two references tying for the best score settle nothing.** They are reported and
    neither is chosen, because picking one would be a guess about which document is in
    front of us, and FR-1.13 reserves that judgement for a person.

    Args:
        text: What was read off the document.
        policy: Read for `min_order_reference_confidence`, the bar a match must clear
            (FR-0.7, NFR-7).
        order_id: This claim's order at ShipBob, if it names one.
        shipment_id: This claim's parcel at ShipBob, if it names one.
        case_number: The case number a merchant would quote.
        case_id: The case's own identifier.

    Returns:
        Whether the document is tied to this claim, what tied it, and everything that was
        considered. A document that cannot be tied is an ordinary answer and never an
        error: it is the answer that stops a wrong recommendation (NFR-4).
    """
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
    """The strongest relationship each reference has with any of this claim's identifiers.

    One entry per reference at most, so a reference that relates to two identifiers cannot
    outvote one that relates firmly to a single identifier. Sorted by score, then by the
    order the references appeared, so ties are stable between runs (NFR-1).
    """
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
    """How firmly one reference relates to one identifier.

    Checked strongest first and stopped at the first that holds, so a reference gets the
    best description of its relationship rather than the last one tried.
    """
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
    """Reduce a reference to the form two of them are compared in.

    Capitals and punctuation are how a number was typed rather than which number it is, so
    `#SO-387378` and `so387378` compare as one thing. Nothing else is removed: two
    references differing by a digit are different numbers and must never compare as equal.
    """
    return _TRIM_PATTERN.sub("", value.casefold())
