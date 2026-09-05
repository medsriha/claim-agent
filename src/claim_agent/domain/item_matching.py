from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.models import OrderLineItem
from claim_agent.policy import Policy

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")
"""Splits a name into words on anything that is not a letter or a digit.

`Pre-Workout` becomes two words, `2.5LBS` becomes `2` and `5lbs` — both of which the
packaging-noise filter below then drops, so the hyphen and the decimal point never have to
be handled specially.
"""

_SIZE_TOKEN = re.compile(r"^\d+[a-z]*$")
"""A word that is entirely digits, or digits followed by a unit, such as `3000` or `24oz`."""

_PACKAGING_NOISE_WORDS: frozenset[str] = frozenset(
    {
        "pack",  # "2 Pack" counts how many are bundled, not what the product is
        "packs",
        "oz",  # a weight unit — the size of a bottle says nothing about which bottle it is
        "lb",
        "lbs",
        "ml",  # a volume unit, same reasoning
        "g",
        "kg",
        "ct",  # ShipBob's own abbreviation for a bundle count, as in "70 ct"
        "count",
        "pc",
        "pcs",
    }
)
"""Words that describe how a product is packaged or sized, never what it is.

Kept deliberately short: every word here is one the sample product names actually use.
Guessing at more would risk stripping a word that happens to be part of a real product
name for some product nobody has looked at yet.
"""

_MIN_SKU_PREFIX_LENGTH = 4
"""How many characters a shared product-code prefix needs before it means anything.

Not a policy value: it is a structural safeguard, not a judgement about a claim. A
one- or two-character prefix is close to certain to happen between two unrelated codes
by coincidence, which would turn "some code overlap" into "no signal at all" the moment
two products happened to share a common brand letter.
"""

_WORD_OVERLAP_CONFIDENCE: dict[int, float] = {1: 0.4, 2: 0.7}
"""How sure shared words alone can make us, by how many significant words are shared.

One shared word is deliberately kept below an ordinary confidence bar: it is exactly
what a shared brand name produces — every product in a catalogue can share one word
with every other — so on its own it must not be able to out-vote the default threshold.
Two shared words is a real pattern. Three or more is about as much as plain text overlap
can support without the names matching outright, so it is capped at 0.8: word overlap
must never outscore an exact name match.
"""


class MatchReason(StrEnum):
    """Which tier of evidence produced a candidate match, strongest first.

    `EXACT_SKU` is the only tier that is ever certain. `SKU_PREFIX` covers a code that
    grew a suffix somewhere between ShipBob's record and the merchant's own paperwork —
    `A00299` on the order, `A00299-LV-8-N` on a receipt. `EXACT_NAME` is a name match once
    capitals and spacing are ignored. `WORD_OVERLAP` is the weakest tier and the one built
    for real merchant wording: `liquid carnitine 3000` sharing "liquid" and "carnitine"
    with `Blue Razz Liquid Carnitine`.
    """

    EXACT_SKU = "exact_sku"
    SKU_PREFIX = "sku_prefix"
    EXACT_NAME = "exact_name"
    WORD_OVERLAP = "word_overlap"


class ItemMatch(BaseModel):
    """One order line that might be the product a merchant claimed, and how sure to be.

    `score` and `reason` say which tier of evidence produced this candidate, and
    `explanation` puts that in one sentence a representative can check against the claim
    themselves rather than take on trust.

    **`is_ambiguous` is true exactly when this candidate ties another one for the highest
    score returned for this claimed product.** A tied top candidate must never be read as
    a match: FR-1.13 forbids picking between two order lines that could equally be what a
    merchant is describing, because they can carry different prices and choosing would
    invent the payout. A caller has to check every returned candidate for this flag —
    a tie means there is no single "best" result to look at instead.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_line: OrderLineItem
    reason: MatchReason
    score: float
    explanation: str
    is_ambiguous: bool = False


def match_items(
    claimed: ClaimedProduct,
    lines: Sequence[OrderLineItem],
    policy: Policy,
) -> tuple[ItemMatch, ...]:
    """Find every order line that could be the product a merchant claimed, with a score.

    Each order line is scored independently against the claimed product, in the tier
    order `MatchReason` describes — a code match beats a name match, which beats two
    names merely sharing words — and only the strongest tier that actually applies to a
    given line is reported for it.

    Every candidate scoring **at or above** `policy.min_item_match_confidence` is
    returned; nothing is left out for having a "good enough" candidate already, because
    a second candidate at the same score is precisely the case a caller has to know
    about (see `ItemMatch.is_ambiguous`). Candidates come back ordered by score, highest
    first, and ties keep the order the order lines were given in, so the same inputs
    always produce the same output (NFR-1).

    Args:
        claimed: The product a merchant's evidence says was damaged, in whatever words
            were read off it.
        lines: The order's line items to score the claimed product against. An empty
            sequence produces no candidates at all — a real answer, not a failure.
        policy: Read for `min_item_match_confidence`, the line below which a candidate is
            too weak to be worth showing a representative (FR-0.7, NFR-7).

    Returns:
        Every order line that could plausibly be the claimed product, scored and
        explained, with ties for the top score flagged rather than resolved. An empty
        tuple means nothing on the order looks enough like the claimed product to
        mention — also a real answer.
    """
    scored: list[tuple[OrderLineItem, MatchReason, float, str]] = []
    for line in lines:
        found = _score(claimed, line)
        if found is None:
            continue
        reason, score, explanation = found
        if score < policy.min_item_match_confidence:
            continue
        scored.append((line, reason, score, explanation))

    # `sorted` is stable, so lines already tied on score keep the order they were passed
    # in — "then by input order" falls out of that rather than needing its own rule.
    ordered = sorted(scored, key=lambda entry: entry[2], reverse=True)
    top_score = ordered[0][2] if ordered else None
    tied_at_top = sum(1 for entry in ordered if entry[2] == top_score) > 1

    return tuple(
        ItemMatch(
            order_line=line,
            reason=reason,
            score=score,
            explanation=explanation,
            is_ambiguous=tied_at_top and score == top_score,
        )
        for line, reason, score, explanation in ordered
    )


def _score(claimed: ClaimedProduct, line: OrderLineItem) -> tuple[MatchReason, float, str] | None:
    """Work out the single strongest tier of evidence that a line is the claimed product.

    Tried strongest first, and the first tier that applies wins: a line already proven by
    a matching code has nothing left for a looser word-overlap rule to add, and checking
    it anyway could only ever lower confidence a firmer tier already earned.

    Returns `None` when no tier applies at all — the ordinary outcome for most lines on
    an order with more than one or two products.
    """
    claimed_sku = _present(claimed.sku)
    line_sku = _present(line.sku)
    if claimed_sku is not None and line_sku is not None:
        left, right = _normalised(claimed_sku), _normalised(line_sku)
        if left == right:
            return (
                MatchReason.EXACT_SKU,
                1.0,
                f'the product code matches exactly ("{line.sku}")',
            )
        if _shares_a_meaningful_prefix(left, right):
            return (
                MatchReason.SKU_PREFIX,
                0.9,
                f'the product code "{claimed_sku}" and the order\'s "{line_sku}" '
                "share a prefix, one being the start of the other",
            )

    if _normalised(claimed.name) == _normalised(line.name):
        return (
            MatchReason.EXACT_NAME,
            0.85,
            f'the name matches exactly once capitals and extra spaces are ignored ("{line.name}")',
        )

    shared = _shared_significant_words(claimed.name, line.name)
    if shared:
        quoted = [f'"{word}"' for word in shared]
        return (
            MatchReason.WORD_OVERLAP,
            _WORD_OVERLAP_CONFIDENCE.get(len(shared), 0.8),
            f"the names share the word{'s' if len(shared) > 1 else ''} {_and_list(quoted)}",
        )

    return None


def _present(value: str | None) -> str | None:
    """A piece of text with something in it, or `None` for blank or missing text alike."""
    if value is None:
        return None
    tidied = value.strip()
    return tidied or None


def _normalised(value: str) -> str:
    """Reduce a name or code to what should count as the same thing.

    Capitals and extra spacing are typing, not meaning, so they are ignored. `casefold`
    rather than `lower` because it does not depend on the language the machine is set to,
    so the same claim matches the same way anywhere (NFR-1).
    """
    return " ".join(value.split()).casefold()


def _shares_a_meaningful_prefix(left: str, right: str) -> bool:
    """True when one of two already-normalised codes starts with the whole of the other.

    Only called once the two are known not to be equal, so a shared prefix here always
    means one code is strictly longer — a real suffix ShipBob's system or the merchant's
    added, such as `A00299` growing into `A00299-LV-8-N`. The shorter code still has to
    clear `_MIN_SKU_PREFIX_LENGTH` for the match to count at all.
    """
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= _MIN_SKU_PREFIX_LENGTH and longer.startswith(shorter)


def _shared_significant_words(claimed_name: str, line_name: str) -> tuple[str, ...]:
    """The significant words two product names have in common.

    Returned in the order the claimed product's own words were written, since that is the
    text a representative is actually holding when they check this. Each word appears at
    most once, even if it appears twice in the claimed name.
    """
    claimed_words = _significant_words(claimed_name)
    line_words = frozenset(_significant_words(line_name))
    return tuple(word for word in claimed_words if word in line_words)


def _significant_words(text: str) -> tuple[str, ...]:
    """Split a product name into the words worth comparing, each kept once, first seen first.

    Packaging noise — a size, a count, a bundle unit — is dropped before anything is
    compared, so two different-sized bottles of the same product still look like the same
    product, and two different products of the same size do not look more alike than they
    are just for sharing a number that says nothing about which product they are.
    """
    seen: dict[str, None] = {}
    for token in _WORD_SPLIT.split(text.casefold()):
        if token and not _is_packaging_noise(token):
            seen.setdefault(token, None)
    return tuple(seen)


def _is_packaging_noise(word: str) -> bool:
    """True for a word that is a size, a count or a unit, and never part of a product's identity.

    Covers a bare noise word from the fixed list above (`oz`), a bare number (`3000`, the
    strength label on a supplement), and the two run together (`24oz`, or `5lbs` — what is
    left of `2.5LBS` once the decimal point has already split it into `2` and `5lbs`).
    """
    if word in _PACKAGING_NOISE_WORDS:
        return True
    if _SIZE_TOKEN.fullmatch(word) is None:
        return False
    letters = word.lstrip("0123456789")
    return letters == "" or letters in _PACKAGING_NOISE_WORDS


def _and_list(parts: Sequence[str]) -> str:
    """Join phrases the way a sentence would, so a reason reads as English."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
