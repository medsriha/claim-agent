from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimLine, MatchOutcome
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import Case, UtcDatetime
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import AmountDerivation


class PrecedentRecord(BaseModel):
    """One damaged product whose claim was closed, kept so a later one like it reads the same.

    **Everything in this store was decided by a person.** A record exists only once a
    representative settled the claim line and that decision took effect (FR-S.1), so there
    is no such thing here as an outcome nobody agreed to, and no record counts for more or
    less than another.

    That is what keeps the store useful rather than circular. If the system's own untested
    suggestions were kept here too, a later investigation would be shown what this system
    already guessed, and repetition would start to look like established practice.

    Holds enough for a person to look at it and say "yes, that is the same situation" or
    "no, it is not" (FR-S.3). A precedent nobody can check is worse than no precedent,
    because it still carries weight.

    `precedent_id` is worked out from the claim line, so closing the same line twice
    replaces the record rather than leaving two versions of it in the store.

    `merchant_account` is the merchant's own description of what happened, in their words.
    It is `None` when the case carried none.

    `outcome` is what the claim actually closed on, and `amount_usd` is what was actually
    paid — `None` when the outcome paid nothing. Both come from ShipBob's records by
    arithmetic, never from a model (FR-1.21). Along with `unit_price` they are kept because
    a representative may want them, and because what a product costs is part of what makes
    two claims alike. **None of the three is ever shown to a model**, which is forbidden to
    write a figure.

    `rep_note` is what the representative said about the decision, where they said anything.

    `withdrawn` takes a record out of future searches without touching it (FR-S.14).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    precedent_id: str
    case_id: str
    claim_line_id: str
    user_id: str | None
    product_name: str
    sku: str | None
    unit_price: Decimal | None
    merchant_account: str | None
    match: MatchOutcome
    evidence: tuple[EvidenceFinding, ...]
    assessments: tuple[Assessment, ...]
    outcome: Recommendation
    amount_usd: Decimal | None
    cap_applied: bool
    rep_note: str | None
    withdrawn: bool
    closed_at: UtcDatetime

    @property
    def evidence_states(self) -> dict[EvidenceKind, EvidenceState]:
        """What state each piece of evidence was in, indexed by which piece it was.

        A kind absent from the record is absent from this mapping rather than appearing as
        missing. The two are different: one means nobody established anything about it, the
        other means it was established to be absent, and collapsing them would let an
        unfinished investigation read as a complete one.
        """
        return {finding.kind: finding.state for finding in self.evidence}


def precedent_id_for(claim_line_id: str) -> str:
    """Name the record for one claim line, the same way every time.

    Worked out from the claim line rather than handed out fresh, so re-investigating
    a line writes over its own record instead of adding a second one that disagrees
    with the first.

    Args:
        claim_line_id: The claim line, for example `CASE-1001-L01`.
    """
    return f"PREC-{claim_line_id}"


def capture_closed_line(
    *,
    case: Case,
    line: ClaimLine,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    outcome: Recommendation,
    amount: AmountDerivation | None,
    closed_at: UtcDatetime,
    rep_note: str | None = None,
) -> PrecedentRecord:
    """Turn one closed claim line into the record we keep (FR-S.1, FR-S.3).

    Called when a representative has decided a claim line and that decision has taken
    effect — never before. A line still in review has no outcome to record, and writing one
    anyway would put this system's own untested suggestion into the store, where a later
    investigation would read it as though somebody had agreed to it.

    Args:
        case: The claim the merchant opened. Only their description of what happened is
            kept; the case's identifiers are recorded so a person can go and read the
            original, and are never compared against (FR-S.4).
        line: The one product this record is about.
        evidence: What was found for each of the four pieces of evidence.
        assessments: The four judgements, where they were made.
        outcome: What the claim line actually closed on — the decision, not a suggestion.
        amount: What was paid, or `None` when the outcome paid nothing. Shown to the
            investigation, which weighs how comparable claims were settled when it
            decides what this one is worth (FR-1.21, FR-S.6).
        closed_at: When the claim was closed. Handed in rather than read from a clock, so
            two runs of the same claim can be compared (NFR-1).
        rep_note: What the representative said about the decision, where they said anything.

    Returns:
        The record to store. Nothing is written here — this only builds the shape.
    """
    return PrecedentRecord(
        precedent_id=precedent_id_for(line.claim_line_id),
        case_id=case.case_id,
        claim_line_id=line.claim_line_id,
        user_id=case.user_id,
        product_name=line.product_name,
        sku=line.sku,
        unit_price=line.unit_price,
        merchant_account=case.description,
        match=line.match,
        evidence=tuple(evidence),
        assessments=tuple(assessments),
        outcome=outcome,
        amount_usd=amount.amount_usd if amount is not None else None,
        cap_applied=amount.cap_applied if amount is not None else False,
        rep_note=rep_note,
        withdrawn=False,
        closed_at=closed_at,
    )


class PrecedentQuery(BaseModel):
    """The claim we are looking for precedent for, reduced to what gets compared.

    Built before the investigation runs, so it holds only what is known by then: the
    merchant's account of what happened, the product, whether that product could be
    tied to a line on the order, and whatever the claim-level pass already settled
    about the evidence (FR-1a.3, FR-S.5).

    `evidence` is usually three of the four pieces rather than all four. The
    photographs of the damaged product are settled per product, during the very
    investigation this query runs before, so they are normally not known yet. That is
    handled by comparing only the pieces both sides know about, rather than by
    guessing at the fourth.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    merchant_account: str | None
    product_name: str
    unit_price: Decimal | None
    match: MatchOutcome
    evidence: tuple[EvidenceFinding, ...] = ()

    @property
    def evidence_states(self) -> dict[EvidenceKind, EvidenceState]:
        """What state each known piece of evidence is in, indexed by which piece it is."""
        return {finding.kind: finding.state for finding in self.evidence}

    @property
    def search_words(self) -> frozenset[str]:
        """The words worth searching the store for.

        The merchant's account and the product name together, reduced to meaningful
        words. This is what narrows the store to a handful of candidates before the
        careful comparison runs.
        """
        return meaningful_words(self.merchant_account) | meaningful_words(self.product_name)


def query_for_line(
    *,
    case: Case,
    line: ClaimLine,
    shared_evidence: Sequence[EvidenceFinding] = (),
) -> PrecedentQuery:
    """Reduce a claim line to the question "what past claims are like this one?" (FR-S.5).

    Args:
        case: The claim the merchant opened, read for their own account of what
            happened. Its identifiers are not part of the question (FR-S.4).
        line: The product about to be investigated.
        shared_evidence: What the claim-level pass settled about the invoice, the
            customer confirmation and the outer packaging (FR-1a.3). Empty when
            nothing has been settled, in which case the evidence pattern simply does
            not take part in the comparison.

    Returns:
        The query. Nothing is read or written here.
    """
    return PrecedentQuery(
        merchant_account=case.description,
        product_name=line.product_name,
        unit_price=line.unit_price,
        match=line.match,
        evidence=tuple(shared_evidence),
    )


# --- How alike two claims are (FR-S.4) --------------------------------------

_WORD = re.compile(r"[a-z]+")
"""Letters only, so an identifier can never be part of what makes two claims alike.

Descriptions in this data open with things like "Shipment ID: 342578703". A number
is exactly the kind of thing FR-S.4 says similarity must not rest on, and dropping
digits at the tokeniser is a surer way to keep them out than remembering to strip
them at every call site.
"""

_SHORTEST_WORD = 3
"""Words shorter than this carry no signal and appear everywhere. "id", "a", "of"."""

_STOPWORDS = frozenset(
    {
        "and",
        "are",
        "but",
        "for",
        "from",
        "had",
        "has",
        "have",
        "its",
        "not",
        "the",
        "that",
        "this",
        "was",
        "were",
        "with",
        "shipment",
        "shipments",
    }
)
"""Words that say nothing about how one claim differs from another.

Ordinary function words, plus "shipment", which opens nearly every description in
this data and would otherwise make every pair of claims look slightly alike.

The list is deliberately short. Stripping more — "damaged", "order", "product" —
would start removing the very words that distinguish one kind of claim from
another, and the words that remain are the ones the comparison rests on.
"""


def meaningful_words(text: str | None) -> frozenset[str]:
    """Reduce text to the set of words worth comparing between two claims.

    Lower-cased, letters only, short words and function words dropped. What comes
    back is a set rather than a list: the same word twice says no more than the
    same word once about whether two claims are alike, and counting it twice would
    let a repetitive description outrank a relevant one.

    Args:
        text: Any text, or `None`. Absent text and blank text both give an empty
            set, which simply takes that comparison out of the reckoning.
    """
    if text is None:
        return frozenset()
    return frozenset(
        word
        for word in _WORD.findall(text.casefold())
        if len(word) >= _SHORTEST_WORD and word not in _STOPWORDS
    )


class PrecedentSimilarity(BaseModel):
    """How alike two claims are, and the reasons in words a person can check.

    `score` runs from nothing to one. `reasons` say what actually matched, so a
    representative shown a precedent can disagree with the comparison rather than
    having to take it on trust (FR-S.3, FR-S.9).

    `reasons` being empty alongside a score above nothing is possible and honest: a
    weak match on one comparison, with nothing worth putting into a sentence.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    score: float
    reasons: tuple[str, ...] = ()


def similarity(query: PrecedentQuery, record: PrecedentRecord) -> PrecedentSimilarity:
    """Score how alike a claim about to be investigated is to one we already did (FR-S.4).

    **Two claims do not have to match on anything to be alike.** Nothing here is an
    equality test: every signal is a matter of degree, and a claim can score well on
    some and badly on others and still come back as the closest thing in the store.
    Similar wording, a similar kind of product, a similar price, a similar pattern of
    missing evidence — any of them pulls two claims together, and none of them is
    required.

    The signals compared today are in `_signals`, which is the list to add to. Each
    one says how much it is worth, how alike the two claims are on it from nothing to
    one, and a sentence saying what it found. Adding a new way for two claims to
    resemble each other is one entry there; nothing else changes.

    **A signal that cannot be compared is left out rather than scored as zero**, and
    the remaining weights are shared out again between the ones that can. A claim
    whose description is missing is not thereby unlike everything — there is simply
    one less thing to go on. Scoring an unavailable signal as zero would push every
    such claim under the threshold and quietly empty the store of them.

    Nothing here reads a clock, a network or a model, so the same pair always scores
    the same (NFR-1).

    Args:
        query: The claim about to be investigated.
        record: One past claim to compare it against.

    Returns:
        A score from 0.0 to 1.0 and the reasons behind it. A score of 0.0 with no
        reasons means nothing at all was found in common.
    """
    compared = [signal for signal in _signals(query, record) if signal.score is not None]
    return PrecedentSimilarity(
        score=_weighted(compared),
        reasons=tuple(signal.reason for signal in compared if signal.reason is not None),
    )


class _Signal(NamedTuple):
    """One way in which two claims can resemble each other.

    `score` runs from nothing to one, or is `None` when this comparison cannot be
    made at all — a price nobody knows, a description nobody wrote. `reason` is the
    sentence a representative reads to check the comparison, and is `None` when there
    is nothing worth saying even though the comparison was made.
    """

    weight: float
    score: float | None
    reason: str | None


def _signals(query: PrecedentQuery, record: PrecedentRecord) -> list[_Signal]:
    """Every way these two claims are compared, with what each is worth.

    **This is the list to extend.** Similarity is open-ended — the carrier, the time
    of year, how the damage was described in the photographs, whether the merchant
    has claimed for this product before — and each of those is one more entry here.
    Nothing else in the file needs to know how many there are.

    The weights are ours and nobody has ruled on them. Unlike the values in
    `policy.py` they are not independently meaningful: only their ratios do anything,
    and an operator cannot sensibly move one without moving the rest. So they are
    named here rather than becoming another handful of levers, and the two knobs that
    *are* worth turning — how many records come back and how close is close enough —
    live in the policy file where an operator will find them.
    """
    return [
        _account_signal(query, record),
        _product_signal(query, record),
        _price_signal(query, record),
        _evidence_signal(query, record),
        _match_signal(query, record),
    ]


def _account_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How alike the merchant's own account of the damage is, word for word.

    Weighted the heaviest, because the description is the fullest account anybody has
    of what actually went wrong.
    """
    asked = meaningful_words(query.merchant_account)
    found = meaningful_words(record.merchant_account)
    shared = asked & found
    return _Signal(
        weight=0.35,
        score=_overlap(asked, found),
        reason=(
            f"the merchant described it in the same words: {_listed(shared)}" if shared else None
        ),
    )


def _product_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How alike the two products are by name, which stands in for what kind of thing broke.

    Word overlap rather than an exact match, deliberately: a "Liposomal Tripeptide
    Collagen" and an "Additional Collagen Ampoule Duo" are different products and are
    the same kind of thing, which is what matters when asking how a claim like this
    one was handled.
    """
    asked = meaningful_words(query.product_name)
    found = meaningful_words(record.product_name)
    shared = asked & found
    return _Signal(
        weight=0.20,
        score=_overlap(asked, found),
        reason=f"the product names share: {_listed(shared)}" if shared else None,
    )


def _price_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How close the two products are in price.

    A claim for a thirty-dollar item and a claim for a five-hundred-dollar one are
    not the same kind of claim, however alike the wording is: what is at stake differs,
    and so does the care a representative takes. Compared as a proportion rather than
    as a difference in dollars, so that a few dollars between two cheap items counts
    for as much as a hundred between two expensive ones.

    `None` when either price is unknown, which is ordinary: a product that matched no
    line on the order has no price at all.
    """
    asked = query.unit_price
    found = record.unit_price
    if asked is None or found is None:
        return _Signal(weight=0.15, score=None, reason=None)

    dearer = max(asked, found)
    if dearer <= 0:
        # Two products both priced at nothing are alike in price, oddly enough, and
        # dividing by the larger of them would not work. Nothing is said about it,
        # because "both cost nothing" is a fact about our records rather than about
        # the claims.
        return _Signal(weight=0.15, score=1.0, reason=None)

    closeness = 1.0 - float(abs(asked - found) / dearer)
    return _Signal(
        weight=0.15,
        score=max(0.0, closeness),
        # The prices are not named in the sentence, which stays a reason rather than a
        # quotation — the figures themselves are rendered beside each record, so naming
        # them here would say the same thing twice in a less useful form.
        reason="the two products cost about the same" if closeness >= 0.8 else None,
    )


def _evidence_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How far the two claims agree about which evidence was there, and which was not.

    Compared only over the pieces **both** sides established something about. The
    query is usually short of the photographs of the damaged product, which are
    settled during the very investigation this runs before, and treating that as a
    disagreement would penalise every candidate for a fact nobody has yet.

    The sentence names the pieces both claims were short of, which is the part of an
    evidence pattern a representative most often recognises.
    """
    asked = query.evidence_states
    found = record.evidence_states
    shared = [kind for kind in REQUIRED_EVIDENCE if kind in asked and kind in found]
    if not shared:
        return _Signal(weight=0.20, score=None, reason=None)

    agreeing = [kind for kind in shared if asked[kind] is found[kind]]
    both_short = [
        kind for kind in agreeing if asked[kind] in (EvidenceState.MISSING, EvidenceState.UNUSABLE)
    ]
    return _Signal(
        weight=0.20,
        score=len(agreeing) / len(shared),
        reason=(
            f"the same evidence was short: {_listed(both_short, sort=False)}"
            if both_short
            else None
        ),
    )


def _match_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """Whether both claims stood in the same relation to the order behind them.

    Only the two unusual outcomes are ever put into a reason: two claims both being
    ordinary says nothing about whether they are alike, whereas two claims both being
    for something that was never ordered says a great deal.
    """
    same = query.match is record.match
    return _Signal(
        weight=0.10,
        score=1.0 if same else 0.0,
        reason=(
            f"the damaged product likewise {_MATCH_IN_WORDS[record.match]}"
            if same and record.match is not MatchOutcome.MATCHED
            else None
        ),
    )


_MATCH_IN_WORDS: dict[MatchOutcome, str] = {
    MatchOutcome.MATCHED: "was one line on the order",
    MatchOutcome.NOT_ON_ORDER: "was on no line of the order",
    MatchOutcome.AMBIGUOUS: "matched more than one line on the order",
}
"""How each match outcome reads in a sentence a representative can follow."""


def _overlap(left: frozenset[str], right: frozenset[str]) -> float | None:
    """How much two sets of words have in common, as a fraction from nothing to one.

    The shared words over the total distinct words — so two identical descriptions
    score one, and two with nothing in common score nothing.

    Returns `None` when either side has no words at all, which means the comparison
    cannot be made rather than that it failed. The caller drops it from the reckoning
    instead of scoring it zero.
    """
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _weighted(signals: Sequence[_Signal]) -> float:
    """Combine the comparisons that could be made into one score from nothing to one.

    The weights are shared out again across whatever is present, so a claim compared
    on three signals is scored out of those three rather than out of all five. That is
    what stops a missing price or a missing description from making a claim look
    unlike everything in the store.

    Returns nothing when no comparison could be made at all, which can happen and is
    honest: two claims with nothing comparable between them are not alike.
    """
    total_weight = sum(signal.weight for signal in signals)
    if total_weight <= 0:
        return 0.0
    return sum(signal.weight * (signal.score or 0.0) for signal in signals) / total_weight


def _listed(words: Sequence[str] | frozenset[str], *, sort: bool = True) -> str:
    """Write a handful of words out for a person to read, in a fixed order.

    Sorted by default, because a set has no order of its own and an unsorted one
    would put the same reason in two different orders on two runs (NFR-1). Anything
    that already has a meaningful order — the four pieces of evidence come in the
    order the requirements list them — passes `sort=False` to keep it.

    The machine-readable names are respaced rather than reworded, so a representative
    sees the same names here as everywhere else.
    """
    listed = sorted(words) if sort else list(words)
    return ", ".join(str(word).replace("_", " ") for word in listed)
