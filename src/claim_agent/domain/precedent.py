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
    """One damaged product whose claim was closed, kept so a later one like it reads the same."""

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
        """What state each piece of evidence was in, indexed by which piece it was."""
        return {finding.kind: finding.state for finding in self.evidence}


def precedent_id_for(claim_line_id: str) -> str:
    """Name the record for one claim line, the same way every time."""
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
    """Turn one closed claim line into the record we keep (FR-S.1, FR-S.3)."""
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
    """The claim we are looking for precedent for, reduced to what gets compared."""

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
        """The words worth searching the store for."""
        return meaningful_words(self.merchant_account) | meaningful_words(self.product_name)


def query_for_line(
    *,
    case: Case,
    line: ClaimLine,
    shared_evidence: Sequence[EvidenceFinding] = (),
) -> PrecedentQuery:
    """Reduce a claim line to the question \"what past claims are like this one?\" (FR-S.5)."""
    return PrecedentQuery(
        merchant_account=case.description,
        product_name=line.product_name,
        unit_price=line.unit_price,
        match=line.match,
        evidence=tuple(shared_evidence),
    )


_WORD = re.compile(r"[a-z]+")
"""Letters only, so an identifier can never be part of what makes two claims alike."""

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
"""Words that say nothing about how one claim differs from another."""


def meaningful_words(text: str | None) -> frozenset[str]:
    """Reduce text to the set of words worth comparing between two claims."""
    if text is None:
        return frozenset()
    return frozenset(
        word
        for word in _WORD.findall(text.casefold())
        if len(word) >= _SHORTEST_WORD and word not in _STOPWORDS
    )


class PrecedentSimilarity(BaseModel):
    """How alike two claims are, and the reasons in words a person can check."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    score: float
    reasons: tuple[str, ...] = ()


def similarity(query: PrecedentQuery, record: PrecedentRecord) -> PrecedentSimilarity:
    """Score how alike a claim about to be investigated is to one we already did (FR-S.4)."""
    compared = [signal for signal in _signals(query, record) if signal.score is not None]
    return PrecedentSimilarity(
        score=_weighted(compared),
        reasons=tuple(signal.reason for signal in compared if signal.reason is not None),
    )


class _Signal(NamedTuple):
    """One way in which two claims can resemble each other."""

    weight: float
    score: float | None
    reason: str | None


def _signals(query: PrecedentQuery, record: PrecedentRecord) -> list[_Signal]:
    """Every way these two claims are compared, with what each is worth."""
    return [
        _account_signal(query, record),
        _product_signal(query, record),
        _price_signal(query, record),
        _evidence_signal(query, record),
        _match_signal(query, record),
    ]


def _account_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How alike the merchant's own account of the damage is, word for word."""
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
    """How alike the two products are by name, which stands in for what kind of thing broke."""
    asked = meaningful_words(query.product_name)
    found = meaningful_words(record.product_name)
    shared = asked & found
    return _Signal(
        weight=0.20,
        score=_overlap(asked, found),
        reason=f"the product names share: {_listed(shared)}" if shared else None,
    )


def _price_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How close the two products are in price."""
    asked = query.unit_price
    found = record.unit_price
    if asked is None or found is None:
        return _Signal(weight=0.15, score=None, reason=None)

    dearer = max(asked, found)
    if dearer <= 0:
        return _Signal(weight=0.15, score=1.0, reason=None)

    closeness = 1.0 - float(abs(asked - found) / dearer)
    return _Signal(
        weight=0.15,
        score=max(0.0, closeness),
        reason="the two products cost about the same" if closeness >= 0.8 else None,
    )


def _evidence_signal(query: PrecedentQuery, record: PrecedentRecord) -> _Signal:
    """How far the two claims agree about which evidence was there, and which was not."""
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
    """Whether both claims stood in the same relation to the order behind them."""
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
    """How much two sets of words have in common, as a fraction from nothing to one."""
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _weighted(signals: Sequence[_Signal]) -> float:
    """Combine the comparisons that could be made into one score from nothing to one."""
    total_weight = sum(signal.weight for signal in signals)
    if total_weight <= 0:
        return 0.0
    return sum(signal.weight * (signal.score or 0.0) for signal in signals) / total_weight


def _listed(words: Sequence[str] | frozenset[str], *, sort: bool = True) -> str:
    """Write a handful of words out for a person to read, in a fixed order."""
    listed = sorted(words) if sort else list(words)
    return ", ".join(str(word).replace("_", " ") for word in listed)
