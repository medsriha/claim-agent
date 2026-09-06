from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from claim_agent.domain.decision import DecisionRecord
from claim_agent.domain.outcome import Recommendation

CENTS = Decimal("0.01")


_ADVISED: dict[Recommendation, str] = {
    Recommendation.APPROVE: "paying the claim",
    Recommendation.APPROVE_HIGH_VALUE: "paying the claim, with a second look at its value",
    Recommendation.REQUEST_INFO: "going back to the merchant for more",
    Recommendation.REQUEST_REP_CLARIFICATION: "asking a representative to clarify it",
}


_DECIDED: dict[Recommendation, str] = {
    Recommendation.APPROVE: "approved it",
    Recommendation.APPROVE_HIGH_VALUE: "approved it as a high-value claim",
    Recommendation.REQUEST_INFO: "went back to the merchant",
    Recommendation.REQUEST_REP_CLARIFICATION: "asked for clarification",
}


def correction_from(decision: DecisionRecord) -> str | None:
    """Write what the system got wrong and what the right answer was, or `None` if it was right."""
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
    if outcome is None:
        return "something else"
    return wording[outcome]


def _money(amount: Decimal | None) -> str:
    """Write an exact amount as a person would read it, never through a float (FR-1.21)."""
    if amount is None:
        return "nothing"
    return f"${amount.quantize(CENTS, ROUND_HALF_UP)}"
