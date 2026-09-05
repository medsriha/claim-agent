from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from claim_agent.domain.decision import DecisionRecord
from claim_agent.domain.outcome import Recommendation

CENTS = Decimal("0.01")

# How each recommendation reads as advice the system gave.
_ADVISED: dict[Recommendation, str] = {
    Recommendation.APPROVE: "paying the claim",
    Recommendation.APPROVE_HIGH_VALUE: "paying the claim, with a second look at its value",
    Recommendation.REQUEST_INFO: "going back to the merchant for more",
    Recommendation.REQUEST_REP_CLARIFICATION: "asking a representative to clarify it",
}

# The same recommendations as something a representative did instead.
_DECIDED: dict[Recommendation, str] = {
    Recommendation.APPROVE: "approved it",
    Recommendation.APPROVE_HIGH_VALUE: "approved it as a high-value claim",
    Recommendation.REQUEST_INFO: "went back to the merchant",
    Recommendation.REQUEST_REP_CLARIFICATION: "asked for clarification",
}


def correction_from(decision: DecisionRecord) -> str | None:
    """Write what the system got wrong and what the right answer was, or `None` if it was right.

    FR-C.2 asks for a correction only where the decision *differs* from the recommendation, and
    for enough words that the next investigation can act on it. So the sentence always carries
    the figures: "the amount was wrong" teaches nothing, and a note that cannot change the next
    run is worse than no note, because it still takes up room in front of the evidence.

    Args:
        decision: What a representative decided, holding both what was advised and what they
            settled on.

    Returns:
        The sentence, or `None` when they agreed with the advice. A representative who only
        reworded the email agrees: FR-2.8 reads rewording as being about how an email reads
        rather than what it says, and only substance is worth remembering.
    """
    if not decision.outcome_changed and not decision.amount_changed:
        return None

    sentence = _what_differed(decision)
    if decision.rep_words is None or not decision.rep_words.strip():
        return sentence
    return f'{sentence} They said: "{decision.rep_words.strip()}"'


def _what_differed(decision: DecisionRecord) -> str:
    advised, decided = decision.recommended, decision.decided
    if decision.outcome_changed:
        return (
            f"The system advised {_words(_ADVISED, advised.outcome)}; "
            f"a representative {_words(_DECIDED, decided.outcome)}"
            f"{_paying(decided.amount_usd)} instead."
        )
    return (
        f"The system worked out {_money(advised.amount_usd)}; "
        f"a representative settled on {_money(decided.amount_usd)} instead."
    )


def _paying(amount: Decimal | None) -> str:
    """The figure a representative settled on, where they settled on one."""
    if amount is None:
        return ""
    return f" and paid {_money(amount)}"


def _words(wording: dict[Recommendation, str], outcome: Recommendation | None) -> str:
    # An outcome is absent only on a claim the quick checks stopped, which has no products and
    # so never reaches this branch — `outcome_changed` is false when either side is missing.
    if outcome is None:
        return "something else"
    return wording[outcome]


def _money(amount: Decimal | None) -> str:
    """Write an exact amount as a person would read it, never through a float (FR-1.21)."""
    if amount is None:
        return "nothing"
    return f"${amount.quantize(CENTS, ROUND_HALF_UP)}"
