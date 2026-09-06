from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.assessment import (
    REQUIRED_ASSESSMENTS,
    Assessment,
    AssessmentName,
    all_answered,
    assessments_by_name,
    failed,
)
from claim_agent.domain.claim_line import ClaimLine, MatchOutcome
from claim_agent.domain.evidence import (
    EvidenceFinding,
    all_present,
    gaps_the_merchant_can_fill,
    gaps_we_caused,
)
from claim_agent.domain.high_value import is_high_value
from claim_agent.domain.reimbursement import AmountDerivation
from claim_agent.policy import Policy


class Recommendation(StrEnum):
    """The next action the system proposes for one claim (FR-1.14, FR-C.7)."""

    APPROVE = "approve"
    APPROVE_HIGH_VALUE = "approve_high_value"
    REQUEST_INFO = "request_info"
    REQUEST_REP_CLARIFICATION = "request_rep_clarification"

    @property
    def is_approval(self) -> bool:
        """True for both ways of recommending a payment."""
        return self in (Recommendation.APPROVE, Recommendation.APPROVE_HIGH_VALUE)


class OverrideReason(StrEnum):
    """Why the rules withheld the payment the agent recommended."""

    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    ASSESSMENT_FAILED = "assessment_failed"
    MERCHANT_DETAILS_UNSPECIFIED = "merchant_details_unspecified"
    EVIDENCE_UNREADABLE = "evidence_unreadable"
    INVESTIGATION_INCOMPLETE = "investigation_incomplete"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PRODUCT_NOT_PRICEABLE = "product_not_priceable"


class OutcomeDecision(BaseModel):
    """The recommendation that stands, and what the agent had said before the rules ran."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    recommendation: Recommendation
    recommended_by_agent: Recommendation
    overrides: tuple[OverrideReason, ...] = ()
    explanation: str
    directed_by_representative: bool = False
    waived: tuple[OverrideReason, ...] = ()

    @property
    def was_overridden(self) -> bool:
        """True when a rule stepped in and withheld what the investigation recommended."""
        return bool(self.overrides)


_WITHHELD_RECOMMENDATION: dict[OverrideReason, Recommendation] = {
    OverrideReason.BUDGET_EXHAUSTED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.EVIDENCE_UNREADABLE: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.INVESTIGATION_INCOMPLETE: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.EVIDENCE_INCOMPLETE: Recommendation.REQUEST_INFO,
    OverrideReason.ASSESSMENT_FAILED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.MERCHANT_DETAILS_UNSPECIFIED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.PRODUCT_NOT_PRICEABLE: Recommendation.REQUEST_REP_CLARIFICATION,
}
"""What each rule leaves in place of the payment it withheld."""

_RECOMMENDATION_IN_WORDS: dict[Recommendation, str] = {
    Recommendation.APPROVE: "paying this claim",
    Recommendation.APPROVE_HIGH_VALUE: "paying this claim, with a second look at its value",
    Recommendation.REQUEST_INFO: "going back to the merchant",
    Recommendation.REQUEST_REP_CLARIFICATION: "asking the representative for clarification",
}
"""Each recommendation as a rep would say it, for the sentence that explains the outcome."""


def decide_outcome(
    recommended_by_agent: Recommendation,
    *,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    lines: Sequence[ClaimLine],
    amount: AmountDerivation | None,
    policy: Policy,
    budget_exhausted: bool = False,
    requested_details: Sequence[str] = (),
    directed_by_representative: bool = False,
) -> OutcomeDecision:
    """Settle what is recommended for one claim, after the rules have had their say."""
    withheld: list[tuple[OverrideReason, str]] = []

    if budget_exhausted:
        withheld.append(
            (
                OverrideReason.BUDGET_EXHAUSTED,
                "the run ran out of steps before it could finish",
            )
        )

    unreadable = gaps_we_caused(evidence)
    if unreadable:
        withheld.append(
            (
                OverrideReason.EVIDENCE_UNREADABLE,
                f"we could not read the {_written_list(_in_words(unreadable))} ourselves",
            )
        )

    merchant_details_named = any(detail.strip() for detail in requested_details)
    if (
        recommended_by_agent is Recommendation.REQUEST_INFO
        and not gaps_the_merchant_can_fill(evidence)
        and not merchant_details_named
    ):
        withheld.append(
            (
                OverrideReason.MERCHANT_DETAILS_UNSPECIFIED,
                "it did not identify a specific missing detail the merchant can provide",
            )
        )

    if recommended_by_agent.is_approval:
        against_approval = _reasons_to_withhold_approval(
            evidence=evidence,
            assessments=assessments,
            lines=lines,
            amount=amount,
        )
        if directed_by_representative and amount is not None and amount.is_payable:
            return _say_if_the_goods_were_expensive(
                _a_representative_directed_it(against_approval, withheld=withheld),
                amount=amount,
                policy=policy,
            )
        withheld.extend(against_approval)

    if not withheld:
        return _say_if_the_goods_were_expensive(
            OutcomeDecision(
                recommendation=recommended_by_agent,
                recommended_by_agent=recommended_by_agent,
                explanation=(
                    "The investigation recommends "
                    f"{_RECOMMENDATION_IN_WORDS[recommended_by_agent]}, and none of the "
                    "rules changed that."
                ),
            ),
            amount=amount,
            policy=policy,
        )

    overrides = tuple(dict.fromkeys(reason for reason, _ in withheld))
    recommendation = _most_cautious(overrides)
    because = _written_list([clause for _, clause in withheld])
    return OutcomeDecision(
        recommendation=recommendation,
        recommended_by_agent=recommended_by_agent,
        overrides=overrides,
        explanation=_explanation(recommended_by_agent, recommendation, because),
    )


def _say_if_the_goods_were_expensive(
    decision: OutcomeDecision, *, amount: AmountDerivation | None, policy: Policy
) -> OutcomeDecision:
    """Label an approval whose damaged goods cost more than the high-value figure (FR-C.7)."""
    if not decision.recommendation.is_approval:
        return decision
    if amount is None or not is_high_value(amount.items_total_usd, policy):
        return decision
    return decision.model_copy(
        update={
            "recommendation": Recommendation.APPROVE_HIGH_VALUE,
            "explanation": (
                f"{decision.explanation} The damaged goods cost "
                f"${amount.items_total_usd:.2f} against the "
                f"${policy.high_value_order_usd:.2f} at which a claim counts as high "
                "value, so this approval wants a second look before anything is sent."
            ),
        }
    )


def _a_representative_directed_it(
    against_approval: Sequence[tuple[OverrideReason, str]],
    *,
    withheld: Sequence[tuple[OverrideReason, str]],
) -> OutcomeDecision:
    """Approve because a representative said to, and record what that set aside."""
    stood_against = (*withheld, *against_approval)
    set_aside = tuple(dict.fromkeys(reason for reason, _ in stood_against))
    return OutcomeDecision(
        recommendation=Recommendation.APPROVE,
        recommended_by_agent=Recommendation.APPROVE,
        directed_by_representative=True,
        waived=set_aside,
        explanation=(
            "A representative directed this payment, setting aside that "
            f"{_written_list([clause for _, clause in stood_against])}."
            if stood_against
            else "A representative directed this payment, and no rule stood against it."
        ),
    )


def _explanation(
    recommended_by_agent: Recommendation, recommendation: Recommendation, because: str
) -> str:
    """Write what the rules did as one sentence a rep can read (NFR-3)."""
    was = _RECOMMENDATION_IN_WORDS[recommended_by_agent]
    now = _RECOMMENDATION_IN_WORDS[recommendation]
    if recommendation is recommended_by_agent:
        return (
            f"The investigation recommended {was}, and the rules reach the same "
            f"recommendation, because {because}."
        )
    return (
        f"The investigation recommended {was}, but {because}, so the recommendation "
        f"is {now} instead."
    )


def _reasons_to_withhold_approval(
    *,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    lines: Sequence[ClaimLine],
    amount: AmountDerivation | None,
) -> list[tuple[OverrideReason, str]]:
    """Collect every rule that forbids the payment the investigation recommended."""
    withheld: list[tuple[OverrideReason, str]] = []

    if not all_present(evidence):
        withheld.append((OverrideReason.EVIDENCE_INCOMPLETE, _evidence_clause(evidence)))

    answered_no = failed(assessments)
    if answered_no:
        withheld.append(
            (
                OverrideReason.ASSESSMENT_FAILED,
                f"it answered no on {_written_list(_in_words(answered_no))}",
            )
        )

    if not all_answered(assessments):
        withheld.append(
            (
                OverrideReason.INVESTIGATION_INCOMPLETE,
                f"it never answered {_written_list(_in_words(_never_answered(assessments)))}",
            )
        )

    not_priceable = _why_not_priceable(lines, amount)
    if not_priceable is not None:
        withheld.append((OverrideReason.PRODUCT_NOT_PRICEABLE, not_priceable))

    return withheld


def _evidence_clause(evidence: Sequence[EvidenceFinding]) -> str:
    """Say what is wrong with the evidence, naming what the merchant can still send."""
    gaps = gaps_the_merchant_can_fill(evidence)
    if not gaps:
        return "the evidence is not all in hand"
    return f"the merchant has still to supply the {_written_list(_in_words(gaps))}"


def _why_not_priceable(lines: Sequence[ClaimLine], amount: AmountDerivation | None) -> str | None:
    """Say why no payment can be worked out for this claim, or `None` if one can."""
    if not lines:
        return "no damaged product was established on this claim"

    unpriceable = next((line for line in lines if not line.is_matched), None)
    if unpriceable is not None:
        if unpriceable.match is MatchOutcome.NOT_ON_ORDER:
            return f"{unpriceable.product_name} is not on the order"
        return (
            f"{unpriceable.product_name} matches more than one line on the order, "
            "and those lines can carry different prices"
        )
    if amount is None:
        return "no amount was worked out for it"
    if not amount.is_payable:
        return _nothing_to_pay_clause(amount)
    return None


def _nothing_to_pay_clause(amount: AmountDerivation) -> str:
    """Say why an amount came to nothing, from the working the amount carries with it."""
    if amount.priced_from is None:
        return "there was no invoice to price it from"
    if not amount.components:
        return f"nothing could be priced from invoice {amount.priced_from}"
    return "the invoice prices the damaged goods at nothing"


def _never_answered(assessments: Sequence[Assessment]) -> tuple[AssessmentName, ...]:
    """Which of the four questions were never answered, in the fixed reporting order."""
    answered = assessments_by_name(assessments)
    return tuple(name for name in REQUIRED_ASSESSMENTS if name not in answered)


def _most_cautious(overrides: Sequence[OverrideReason]) -> Recommendation:
    """Pick the most cautious of the recommendations the rules that stepped in left."""
    left_standing = {_WITHHELD_RECOMMENDATION[override] for override in overrides}
    if Recommendation.REQUEST_REP_CLARIFICATION in left_standing:
        return Recommendation.REQUEST_REP_CLARIFICATION
    return Recommendation.REQUEST_INFO


def _in_words(names: Sequence[str]) -> list[str]:
    """Write machine-readable names as words: `outer_packaging_photo` as \"outer packaging photo\"."""
    return [name.replace("_", " ") for name in names]


def _written_list(items: Sequence[str]) -> str:
    """Join things into the list a person would write: \"a\", \"a and b\", \"a, b and c\"."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
