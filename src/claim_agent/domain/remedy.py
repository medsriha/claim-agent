from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_MAX_TEXT_LENGTH = 2000
"""How much of the text this will scan before giving up on the rest.

Merchant prose is untrusted input: it arrives already read out of an image or an email by
a model, and nothing stops it from being enormous, accidentally or otherwise. Two thousand
characters is comfortably longer than any merchant message in the sample data, so nothing
real is cut short by it, and short enough that a pathological wall of text cannot make a
supposedly instant keyword check slow.
"""

_PART_WINDOW = 25
"""How many characters either side of the word "replacement" counts as "nearby".

Wide enough to catch "a lid replacement for my roller" — "lid" sits four characters
before "replacement" — and narrow enough that an unrelated part mentioned earlier in a
long sentence is not dragged in by accident.
"""

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
"""Words for a single component of a product, rather than the product itself.

Deliberately everyday and short: CASE-1004's merchant asks for a "lid replacement" for a
roller, not a replacement roller, and this is the list of nouns that turns a request for
a whole item into a request for one part of it. Kept as a tuple, not a set, so the search
below always checks them in the same order — a text that happens to mention two of these
words must still produce the same answer on every run (NFR-1).
"""

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
"""Phrases that ask for the whole order to go out again, as CASE-1002's "send me my
package in its entirety" does — a different request from replacing one damaged item.
"""


class RemedyKind(StrEnum):
    """What a merchant's own words are asking ShipBob to do about a claim.

    `REFUND` and `REPLACEMENT` both make the merchant whole for the item itself — one
    with money, one with the same product again. `REPLACEMENT_PART` is narrower: a single
    broken component, not the item — CASE-1004 asks for a lid, not a whole roller.
    `RESHIP` is a request for the original order to go out again in full, rather than one
    item replaced. `UNCLEAR` is not a match at all: it is what this reads back when
    nothing in the text recognisably asked for anything, which is a correct answer and
    never a failure of the rule.
    """

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
    """One remedy a merchant's words appear to ask for, and the exact words that said so.

    `matched_phrase` is quoted directly from the original text, never paraphrased, so a
    representative can search the merchant's own message for it and judge the rule's
    reasoning for themselves rather than take it on trust.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RemedyKind
    matched_phrase: str


class RemedyReading(BaseModel):
    """Every remedy a merchant's own words seem to ask for, read by a fixed set of keyword rules.

    Attributes:
        requested: One entry per distinct remedy the text triggered — never `UNCLEAR`
            itself, since nothing "triggers" the absence of a finding. CASE-1002's either/or
            wording produces two entries, `REFUND` and `RESHIP`, because the text really
            does ask for both, leaving the choice to ShipBob.
        truncated: True when the text was longer than this module scans and the tail of it
            was never read. A rep seeing this should treat `requested` as a partial answer:
            something further along the message could have changed it.
        reason: One plain sentence a representative can agree or disagree with.
    """

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
    """Say which remedies a merchant's own words recognisably ask for, and quote the words.

    Runs three independent checks over the text — a refund, a replacement (whole item or
    a single part), and a reshipment — and reports every one that fired. None of this
    reads the text for meaning: it looks for a short, fixed list of phrases, in the order
    the phrases are listed above, and reports the first phrase from each list that
    matches. A merchant who never uses one of these words, however clearly they are
    asking for that remedy some other way, gets `UNCLEAR` for it — see the module
    docstring for why that is an honest limit rather than a bug to route around.

    Args:
        text: The merchant's own words, already read out of an email, a screenshot, or a
            case description by something else. Only the first `_MAX_TEXT_LENGTH`
            characters are scanned, because this text arrived from outside the system and
            nothing bounds how long it could be.

    Returns:
        Every remedy kind the text recognisably asked for, each with the exact phrase
        that triggered it. An empty result is `UNCLEAR` and is exactly as valid an answer
        as a full one — never resolved by guessing at silence.
    """
    scanned = text[:_MAX_TEXT_LENGTH]
    # `lower`, not `casefold`: what matters here is that a match's character positions in
    # the lower-cased copy line up exactly with the original, so the phrase quoted back
    # to a rep is copied from what the merchant actually wrote. `casefold` can change a
    # string's length for some scripts, which would throw that alignment off.
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
    """The original-text phrase matched by the first of these patterns to fire, or `None`.

    Patterns are tried in the order given and the search stops at the first hit, so a
    text matching several phrases for the same remedy always reports the same one.
    """
    for pattern in patterns:
        match = pattern.search(lowered)
        if match is not None:
            return original[match.start() : match.end()]
    return None


def _classify_replacement(original: str, lowered: str) -> RemedyMatch | None:
    """Read the first "replace"/"replacement" in the text, and say what it is asking for.

    A bare "replacement" asks for the whole item again. One with a part word — "lid",
    "cap", "handle" — within `_PART_WINDOW` characters of it asks for just that part,
    which is CASE-1004's case exactly. Only the first occurrence in the text is read;
    a message asking about two different replacements would need a person regardless of
    what this says.
    """
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
    """The first of `words`, in the order given, that appears whole in `window`.

    Returns the word and its start and end position within `window`, so the caller can
    line it up with the rest of the original text.
    """
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
