from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_MAX_TEXT_LENGTH = 2000
"""How much of the text this will scan before giving up on the rest."""

_PART_WINDOW = 25
"""How many characters either side of the word \"replacement\" counts as \"nearby\"."""

_PART_WORDS: tuple[str, ...] = (
    "lid",
    "cap",
    "cover",
    "handle",
    "part",
    "piece",
    "component",
    "knob",
    "strap",
    "button",
    "lever",
    "spout",
    "valve",
    "seal",
    "hinge",
)
"""Words for a single component of a product, rather than the product itself."""

_REPLACEMENT_WORD = re.compile(r"\breplac(?:e|ed|ement|ing)\b")
"""Any form of the word "replace" — the verb somebody uses to ask for one, not a refund."""

_REFUND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brefunds?\b"),
    re.compile(r"\bmoney\s+back\b"),
)
"""Phrases that ask for money back rather than another item."""

_RESHIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bresh(?:ip|ipped|ipment)\w*\b"),
    re.compile(r"\bresend\w*\b"),
    re.compile(r"\bsend\b[^.?!]{0,40}\bpackage\b"),
    re.compile(r"\bsend\b[^.?!]{0,40}\bagain\b"),
)
"""Phrases that ask for the whole order to go out again, as CASE-1002's \"send me my"""


class RemedyKind(StrEnum):
    """What a merchant's own words are asking ShipBob to do about a claim."""

    REFUND = "refund"
    REPLACEMENT = "replacement"
    REPLACEMENT_PART = "replacement_part"
    RESHIP = "reship"
    UNCLEAR = "unclear"


_LABEL: dict[RemedyKind, str] = {
    RemedyKind.REFUND: "a refund",
    RemedyKind.REPLACEMENT: "a replacement of the whole item",
    RemedyKind.REPLACEMENT_PART: "a replacement part rather than the whole item",
    RemedyKind.RESHIP: "the order sent again",
}


class RemedyMatch(BaseModel):
    """One remedy a merchant's words appear to ask for, and the exact words that said so."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RemedyKind
    matched_phrase: str


class RemedyReading(BaseModel):
    """Every remedy a merchant's own words seem to ask for, read by a fixed set of keyword rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested: tuple[RemedyMatch, ...] = ()
    truncated: bool = False
    reason: str

    @property
    def kinds(self) -> tuple[RemedyKind, ...]:
        """Just the remedy kinds requested, in the order they were found."""
        return tuple(match.kind for match in self.requested)

    @property
    def is_unclear(self) -> bool:
        """True when nothing recognisable was found — a real answer, never a failure."""
        return not self.requested


def classify_remedy(text: str) -> RemedyReading:
    """Say which remedies a merchant's own words recognisably ask for, and quote the words."""
    scanned = text[:_MAX_TEXT_LENGTH]

    lowered = scanned.lower()

    requested: list[RemedyMatch] = []

    refund_phrase = _first_match(scanned, lowered, _REFUND_PATTERNS)
    if refund_phrase is not None:
        requested.append(RemedyMatch(kind=RemedyKind.REFUND, matched_phrase=refund_phrase))

    replacement_match = _classify_replacement(scanned, lowered)
    if replacement_match is not None:
        requested.append(replacement_match)

    reship_phrase = _first_match(scanned, lowered, _RESHIP_PATTERNS)
    if reship_phrase is not None:
        requested.append(RemedyMatch(kind=RemedyKind.RESHIP, matched_phrase=reship_phrase))

    return RemedyReading(
        requested=tuple(requested),
        truncated=len(text) > _MAX_TEXT_LENGTH,
        reason=_reason_for(requested),
    )


def _first_match(original: str, lowered: str, patterns: Sequence[re.Pattern[str]]) -> str | None:
    """The original-text phrase matched by the first of these patterns to fire, or `None`."""
    for pattern in patterns:
        match = pattern.search(lowered)
        if match is not None:
            return original[match.start() : match.end()]
    return None


def _classify_replacement(original: str, lowered: str) -> RemedyMatch | None:
    """Read the first \"replace\"/\"replacement\" in the text, and say what it is asking for."""
    replacement = _REPLACEMENT_WORD.search(lowered)
    if replacement is None:
        return None

    window_start = max(0, replacement.start() - _PART_WINDOW)
    window_end = min(len(lowered), replacement.end() + _PART_WINDOW)
    nearby_part = _first_word_in(lowered[window_start:window_end], _PART_WORDS)

    if nearby_part is None:
        phrase = original[replacement.start() : replacement.end()]
        return RemedyMatch(kind=RemedyKind.REPLACEMENT, matched_phrase=phrase)

    _word, relative_start, relative_end = nearby_part
    part_start = window_start + relative_start
    part_end = window_start + relative_end
    span_start = min(part_start, replacement.start())
    span_end = max(part_end, replacement.end())
    phrase = original[span_start:span_end].strip(" ,.;:!?")
    return RemedyMatch(kind=RemedyKind.REPLACEMENT_PART, matched_phrase=phrase)


def _first_word_in(window: str, words: Sequence[str]) -> tuple[str, int, int] | None:
    """The first of `words`, in the order given, that appears whole in `window`."""
    for word in words:
        match = re.search(rf"\b{re.escape(word)}\b", window)
        if match is not None:
            return word, match.start(), match.end()
    return None


def _reason_for(requested: Sequence[RemedyMatch]) -> str:
    """One plain sentence summarising what was found, or saying honestly that nothing was."""
    if not requested:
        return (
            "Nothing in this text recognisably asked for a refund, a replacement, a "
            "replacement part, or the order sent again. That is a real answer: guessing "
            "at what was not said would be worse than reporting it as unclear."
        )
    labels = [_LABEL[match.kind] for match in requested]
    return f"The merchant's own words ask for {_and_list(labels)}."


def _and_list(parts: Sequence[str]) -> str:
    """Join phrases the way a sentence would, so a reason reads as English."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
