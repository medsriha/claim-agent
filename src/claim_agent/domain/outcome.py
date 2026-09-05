"""The next actions that can be proposed for a claim, and who gets to choose.

Every claim ends in one of four actions and nothing else (FR-1.14, FR-C.7): approve
it, approve it and say the damaged goods were expensive, ask the merchant for a specific
detail, or ask the representative for clarification. Each is a **proposal to a rep**. None
of them takes effect on its own, and no amount of confidence changes that (FR-1.17,
FR-3.1).

One claim gets one action, however many products are on it, and where the products point
different ways the most cautious of them wins (FR-1b.3).

Three of the four are the agent's to choose. It weighs the evidence, the assessments, and
its confidence, then proposes the appropriate next action. Refusal and escalation are not
alternate outcomes hidden behind this contract. The fourth is code's alone: whether the
damaged goods were expensive is arithmetic, and FR-C.7 requires it to stay that way.

There is one narrow exception, and its direction is the whole point: **code can
withhold a recommendation of payment that the requirements forbid, and can never
move a recommendation towards paying.** Three of the requirements are written as
rules rather than judgements — evidence that is missing or unusable means asking
the merchant (FR-1.6), confidence below the threshold means handing it to a person
(FR-1.15), and a step budget that ran out means the same (FR-1.16) — and a rule
that the model is merely asked to follow is not a rule. So they are applied to its
answer afterwards.

When that happens, what the agent originally recommended is kept beside the result.
A rep should be able to see that the rules disagreed with the investigation, rather
than seeing only the outcome and wondering how it was reached (NFR-3).

The high-value label is not an exception to any of that, because it withholds nothing.
An approval that survives every rule above is still that approval, for the same money on
the same evidence; the label only says that the damaged goods were expensive, so the
person deciding sees it before they act rather than afterwards (FR-C.7).

Nothing here reaches out to anything and nothing here reads a clock.
"""

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
    lowest_confidence,
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
    """The next action the system proposes for one claim (FR-1.14, FR-C.7).

    `APPROVE` proposes paying the merchant. `APPROVE_HIGH_VALUE` proposes exactly the
    same payment, on the same evidence, and says as well that the damaged goods cost more
    than the high-value figure in the claim policy, so a representative should take a
    second look before sending anything (FR-0.5, FR-C.7). Both carry an amount; nothing
    else does. `REQUEST_INFO` proposes going back to the merchant for something
    specific — the outcome whenever a piece of evidence is missing or unusable (FR-1.6).
    `REQUEST_REP_CLARIFICATION` asks the representative to resolve something incorrect,
    ambiguous, or insufficiently reliable. It is where uncertainty and internal failures
    end up (FR-1.15, FR-1.16, NFR-4), and it never produces a merchant email.

    **The high-value approval is code's to choose and never the agent's.** FR-C.7 is
    explicit that a rule about expensive claims has to be a rule: a model asked to be
    more careful about them would flag the same claim one day and not the next (NFR-1).
    So the agent picks from the other three and a deterministic comparison adds this one.

    There is deliberately no denial or escalation value. A run that cannot safely approve
    or ask the merchant for a specific detail asks the representative for clarification.
    """

    APPROVE = "approve"
    APPROVE_HIGH_VALUE = "approve_high_value"
    REQUEST_INFO = "request_info"
    REQUEST_REP_CLARIFICATION = "request_rep_clarification"

    @property
    def is_approval(self) -> bool:
        """True for both ways of recommending a payment.

        Everything that treats an approval differently — carrying an amount, drafting the
        merchant's email, counting towards the claim-wide cap — has to mean both of them.
        Comparing against `APPROVE` alone would let a high-value approval slip past the
        cap and reach a merchant with no figure in its email.
        """
        return self in (Recommendation.APPROVE, Recommendation.APPROVE_HIGH_VALUE)


class OverrideReason(StrEnum):
    """Why the rules withheld the payment the agent recommended.

    `EVIDENCE_INCOMPLETE` means a required piece of evidence was missing or
    unusable, so the merchant is asked for it instead (FR-1.6). It is the one reason
    here that sends a request to the merchant, and it is deliberately the only one:
    a merchant can only be asked for something they can actually supply.

    The next two are the mirror of that. `EVIDENCE_UNREADABLE` means we could not
    read an image ourselves, and `INVESTIGATION_INCOMPLETE` means the run never
    answered one of the four questions. Both are our own shortcomings rather than
    anything the merchant left out, so both go to a person (NFR-4). Asking a
    merchant to send a photograph again because our download failed, or because we
    did not finish looking at the one they sent, is a request they cannot act on —
    the pre-flight screen has one label that makes this mistake already, and
    DESIGN.md records it as a fault rather than a pattern to copy.
    `NOT_CONFIDENT_ENOUGH` means the overall action confidence or the weakest supporting
    assessment fell below the threshold in the policy file (FR-1.15).
    `BUDGET_EXHAUSTED` means the run ran out of steps
    before it could finish, and whatever it established is carried forward rather
    than being thrown away (FR-1.16). `PRODUCT_NOT_PRICEABLE` means the damaged
    product could not be tied to exactly one line on the order, so there is no
    price to pay from (FR-1.13, FR-1a.2).

    `PRODUCT_NOT_PRICEABLE` applies to the claim as a whole: if any one damaged
    product cannot be tied to exactly one line on the order, nothing on the claim is
    paid. Choosing the likelier candidate would invent the payout, and paying for the
    products that did match while ignoring one that did not would settle a claim
    nobody has established the shape of.

    **There is deliberately no reason here for the reimbursement cap.** A claim
    recommends one figure and the cap is applied where that figure is read, before
    this function sees it (FR-1.20). Nothing is withheld by it — a proposal over the
    cap becomes the cap and says so.
    """

    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    ASSESSMENT_FAILED = "assessment_failed"
    MERCHANT_DETAILS_UNSPECIFIED = "merchant_details_unspecified"
    EVIDENCE_UNREADABLE = "evidence_unreadable"
    INVESTIGATION_INCOMPLETE = "investigation_incomplete"
    NOT_CONFIDENT_ENOUGH = "not_confident_enough"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PRODUCT_NOT_PRICEABLE = "product_not_priceable"


class OutcomeDecision(BaseModel):
    """The recommendation that stands, and what the agent had said before the rules ran.

    `recommendation` is what a rep is shown. `recommended_by_agent` is what the
    investigation itself concluded. When the two differ, `overrides` says which
    rules stepped in and `explanation` says so in a sentence a rep can read.

    The two being equal is the ordinary case, and it is worth being able to tell
    that apart from "the rules had nothing to say" — hence keeping both rather than
    only recording a difference.

    There is one way the two differ with `overrides` empty: an approval the rules left
    alone, on damaged goods dear enough to be worth a second look, is recommended as a
    high-value approval (FR-C.7). Nothing was withheld, so nothing is listed as having
    stepped in; the explanation names the two figures that decided it.

    `directed_by_representative` means a representative told the agent what to do and it
    did it. The rules that would have withheld the payment are then in `waived` rather
    than in `overrides`: they were evaluated, they applied, and a person set them aside.
    Keeping them is the whole point — an approval a representative directed and one the
    evidence earned must never look the same in the record (NFR-5, FR-C.1).

    **The reimbursement cap is not among the things that can be waived**, because it is
    not applied here at all. A figure is capped where it is read, in
    `claim_agent.domain.reimbursement`, before this function ever sees it (FR-1.20).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    recommendation: Recommendation
    recommended_by_agent: Recommendation
    overrides: tuple[OverrideReason, ...] = ()
    explanation: str
    directed_by_representative: bool = False
    waived: tuple[OverrideReason, ...] = ()

    @property
    def was_overridden(self) -> bool:
        """True when a rule stepped in and withheld what the investigation recommended.

        Not the same as the recommendation having changed, and the difference is
        real: an investigation that already recommended handing the claim to a
        representative, on a claim a rule would also have sent for clarification, has a rule recorded
        here while `recommendation` and `recommended_by_agent` are identical. The
        rule did apply; it simply agreed. Compare the two fields directly if what
        you want to know is whether the answer moved.
        """
        return bool(self.overrides)


_WITHHELD_RECOMMENDATION: dict[OverrideReason, Recommendation] = {
    OverrideReason.BUDGET_EXHAUSTED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.EVIDENCE_UNREADABLE: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.INVESTIGATION_INCOMPLETE: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.EVIDENCE_INCOMPLETE: Recommendation.REQUEST_INFO,
    OverrideReason.ASSESSMENT_FAILED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.MERCHANT_DETAILS_UNSPECIFIED: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.NOT_CONFIDENT_ENOUGH: Recommendation.REQUEST_REP_CLARIFICATION,
    OverrideReason.PRODUCT_NOT_PRICEABLE: Recommendation.REQUEST_REP_CLARIFICATION,
}
"""What each rule leaves in place of the payment it withheld.

Only two of the four actions can be reached this way. A rule can send the
claim back to the merchant for something specific, or ask the representative; no rule
can pay, and no rule refuses a claim outright, because refusing is a judgement
about the merits and these are not judgements (FR-1.14).
"""

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
    confidence: float = 1.0,
    directed_by_representative: bool = False,
) -> OutcomeDecision:
    """Settle what is recommended for one claim, after the rules have had their say.

    The investigation has already decided what it would do. This applies the handful of
    requirements that are written as rules rather than judgements, and it can only ever
    push in one direction: **it can withhold a payment the requirements forbid, and it
    can never move a recommendation towards paying.** A merchant information request
    and a representative clarification request are left alone unless their own contract
    is invalid (FR-1.14).

    Two rules apply whatever was recommended, because neither is about the merits of the
    claim. A run that used up its step budget did not finish, so it has not established a
    safe final action, and it goes to a person with whatever it did establish
    (FR-1.16). Evidence we could not read ourselves is our failure, and it goes to a
    person too — never back to the merchant, who can do nothing about our download
    (FR-1.7, NFR-4).

    The rest apply only to a recommendation of payment: evidence that is not all in hand
    (FR-1.6), a question answered no (FR-1.12), a question never answered at all,
    confidence under the threshold in the claim policy (FR-1.15), and any damaged product
    that cannot be tied to one price (FR-1.13, FR-1a.2).

    An approval that survives all of them is looked at once more, and labelled a
    high-value approval when the damaged goods cost more than the high-value figure
    (FR-C.7). That takes nothing away and adds no condition: it is the same payment, said
    in a way a representative cannot approve without noticing.

    Those middle two look alike and are not. A question answered no means something
    appears incorrect in the claim. A question left unanswered is a finding about *us* —
    the run stopped early, or lost its way. Both need representative clarification and
    neither generates merchant wording, but the report preserves which one happened.

    **Every rule that applies is reported, not just the first.** A rep should see
    everything that was wrong with the claim rather than fixing one thing and discovering
    the next, so the checks all run and their reasons are collected — the same habit the
    pre-flight screen has. Where several apply, the recommendation left standing is the
    most cautious of them: handing the claim to a person beats going back to the
    merchant, because a person can do either and the merchant cannot (NFR-4).

    There is no clock, no network and no model here, so the same claim always decides the
    same way (NFR-1).

    Args:
        recommended_by_agent: What the investigation concluded. Kept on the result
            whether or not it survives, so a rep can see that the rules disagreed with
            the investigation rather than only seeing the outcome (NFR-3).
        evidence: What was found for each of the four pieces of evidence. A piece not
            mentioned at all counts as not having it.
        assessments: The four judgements made once the evidence was in. May be short or
            empty, which is an unfinished investigation rather than a clean one.
        lines: Every damaged product on the claim, read for whether each matched exactly
            one line on the order. One unmatched product withholds the whole claim: it has
            no single price to pay from, and paying for its neighbours instead would settle
            a claim nobody has established the shape of. Empty means nothing was
            established as damaged, which is never a reason to pay.
        amount: What a payment would come to, as worked out by code. `None` when no
            amount was worked out at all, which is never a reason to pay.
        policy: Read for the lowest confidence a payment may be recommended on
            (FR-0.7, NFR-7).
        budget_exhausted: True when the run ran out of steps before it could finish.
        requested_details: Specific additional information the agent says the merchant
            can provide. A request without this or a merchant-fillable evidence gap is
            incomplete and goes to the representative instead.
        confidence: The agent's confidence in its overall next action. Approval must
            clear the same threshold as each supporting assessment.
        directed_by_representative: True when a representative told the agent to approve
            this claim and it is carrying out that instruction rather than recommending
            one of its own. **The rules that would have withheld the payment are then
            set aside**, and recorded in `waived` so the report can say what a person
            overruled. Never true on a first pass: nobody has said anything yet.

            This is deliberate and it is a departure from FR-R.8, taken as a product
            decision. **The reason is that the agent can be wrong, and the representative
            is what corrects it.** Every rule below encodes the agent's own uncertainty —
            it will not pay while a photograph is missing because *it* cannot tell what
            the photograph would have shown. A representative can: they know the merchant,
            they can see the claim, and they may have the evidence somewhere this system
            cannot read. Refusing them is the agent insisting it is right about the very
            thing it is worst at, and it leaves a person with no way to act on their own
            judgement except to argue with a machine. What survives untouched is the cap, because it is
            applied where a figure is read rather than here, and the rule that no figure
            the model wrote reaches a merchant (FR-1.20, FR-1.21). A directed approval
            with nothing payable is still refused, because there would be no figure to
            put in the email — the agent asks what to pay instead.

    Returns:
        The recommendation that stands, what the investigation had said, every rule that
        stepped in, and one sentence a rep can read saying what happened.
    """
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
            policy=policy,
            confidence=confidence,
        )
        if directed_by_representative and amount is not None and amount.is_payable:
            # A representative told the agent to approve, and there is a figure to
            # approve. Every rule that would have withheld it is set aside and written
            # down instead, so the record shows exactly what a person overruled rather
            # than an approval that looks like one the evidence earned.
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

    # A dictionary rather than a set, for the reasons and nothing else: two rules can
    # give the same reason and it should be listed once, and iterating a set would put
    # the reasons in an order that can differ between runs (NFR-1). Every clause is
    # kept, so a reason arrived at two ways still explains both.
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
    """Label an approval whose damaged goods cost more than the high-value figure (FR-C.7).

    Only ever called on a decision no rule withheld, so a claim that could not be approved
    is never labelled instead of being sent where it belongs. The label withholds nothing
    itself: the same money is recommended on the same evidence, and what changes is that a
    representative is told the goods were dear before they act on it. That is why the
    reason does not appear in `overrides`, which is a list of payments the rules refused.

    What is compared is what the damaged items cost on the invoice, not what would be
    paid for them. A payment can never exceed the reimbursement cap, so comparing it with
    a threshold several times that size would label nothing, ever (FR-1.20).

    A payment a representative directed is labelled like any other. It states a fact about
    the claim rather than standing in anybody's way, and whoever reads the report next may
    not be the person who gave the instruction.
    """
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
    """Approve because a representative said to, and record what that set aside.

    The explanation names every rule a person overruled, in the rules' own words, because a
    payment released this way and one the evidence earned must be told apart at a glance by
    whoever reads the report afterwards (NFR-3, NFR-5).

    An approval nothing would have withheld is still marked as directed. That the
    representative asked for it is a fact about how the decision was reached, and it is worth
    recording whether or not it made any difference.
    """
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
    """Write what the rules did as one sentence a rep can read (NFR-3).

    Says "instead" only when the recommendation actually changed. A run that ran out of
    steps having already decided to hand the claim to a person changes nothing, and a
    sentence claiming otherwise would be the kind of small untruth that costs a reader
    their trust in the rest of the report.
    """
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
    policy: Policy,
    confidence: float,
) -> list[tuple[OverrideReason, str]]:
    """Collect every rule that forbids the payment the investigation recommended.

    Each entry is a reason and one clause saying what happened, in the order the
    requirements set the rules out: evidence first, then the four questions, then
    confidence, then whether the product can be priced at all. The order settles how the
    sentence reads and nothing else — no reason is dropped by being last, and the
    recommendation does not depend on it.

    Returns an empty list when the payment may stand.
    """
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

    assessment_confidence = lowest_confidence(assessments)
    weakest = (
        confidence if assessment_confidence is None else min(confidence, assessment_confidence)
    )
    if weakest < policy.min_assessment_confidence:
        withheld.append((OverrideReason.NOT_CONFIDENT_ENOUGH, _confidence_clause(weakest, policy)))

    not_priceable = _why_not_priceable(lines, amount)
    if not_priceable is not None:
        withheld.append((OverrideReason.PRODUCT_NOT_PRICEABLE, not_priceable))

    return withheld


def _evidence_clause(evidence: Sequence[EvidenceFinding]) -> str:
    """Say what is wrong with the evidence, naming what the merchant can still send.

    When every gap is one we caused, there is nothing to name here: asking a merchant to
    send a photograph again because our own download failed is a request they cannot act
    on (FR-1.7). That case is reported as our own failure alongside this one, so the
    clause says only that the evidence is short.
    """
    gaps = gaps_the_merchant_can_fill(evidence)
    if not gaps:
        return "the evidence is not all in hand"
    return f"the merchant has still to supply the {_written_list(_in_words(gaps))}"


def _confidence_clause(weakest: float | None, policy: Policy) -> str:
    """Compare the lowest assessment or overall-action confidence with the threshold.

    Both figures are written to two decimal places, so the same claim reads identically
    every time rather than depending on how a fraction happens to print (NFR-1).

    Neither wording carries a comma of its own. Several of these clauses are read out in
    one sentence, and a comma inside one of them would look like the next item in the
    list.
    """
    required = f"{policy.min_assessment_confidence:.2f}"
    if weakest is None:
        return f"nothing was assessed and so nothing met the {required} confidence needed"
    return f"its lowest reported confidence was {weakest:.2f} against the {required} needed"


def _why_not_priceable(lines: Sequence[ClaimLine], amount: AmountDerivation | None) -> str | None:
    """Say why no payment can be worked out for this claim, or `None` if one can.

    A product that matched no order line, or several, has no single price to pay from,
    and the requirements are explicit that the system must ask rather than pick the
    likeliest candidate (FR-1.13, FR-1a.2). **One such product withholds the whole
    claim**, because the claim recommends a single figure and there is no honest figure
    while part of what it covers has no price.

    A claim with no damaged products established is refused for the same reason: there is
    nothing to pay for. An amount of nothing is not payable either, however it arose, and
    the reason it arose is worth stating — a rep can chase a missing invoice, and nobody
    has ever said what a free item does to a claim.
    """
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
    """Say why an amount came to nothing, from the working the amount carries with it.

    Three things produce nothing, and a rep can act on the first two: there was no
    invoice to price from, nothing on the invoice could be matched to the damaged
    product, or the invoice genuinely prices the product at nothing.
    """
    if amount.priced_from is None:
        return "there was no invoice to price it from"
    if not amount.components:
        return f"nothing could be priced from invoice {amount.priced_from}"
    return "the invoice prices the damaged goods at nothing"


def _never_answered(assessments: Sequence[Assessment]) -> tuple[AssessmentName, ...]:
    """Which of the four questions were never answered, in the fixed reporting order.

    A question nobody answered is a gap in the investigation, which is a different thing
    from a question answered no — and neither may be mistaken for one that passed.
    """
    answered = assessments_by_name(assessments)
    return tuple(name for name in REQUIRED_ASSESSMENTS if name not in answered)


def _most_cautious(overrides: Sequence[OverrideReason]) -> Recommendation:
    """Pick the most cautious of the recommendations the rules that stepped in left.

    Handing the claim to a person beats going back to the merchant: a person can do
    either, and can also see that the merchant was never the problem (NFR-4).

    Only ever called with at least one rule in hand, so falling back to going back to the
    merchant cannot quietly stand in for "no rule applied".
    """
    left_standing = {_WITHHELD_RECOMMENDATION[override] for override in overrides}
    if Recommendation.REQUEST_REP_CLARIFICATION in left_standing:
        return Recommendation.REQUEST_REP_CLARIFICATION
    return Recommendation.REQUEST_INFO


def _in_words(names: Sequence[str]) -> list[str]:
    """Write machine-readable names as words: `outer_packaging_photo` as "outer packaging photo".

    Nothing is reworded, only respaced. These are the system's own names for the four
    pieces of evidence and the four questions, and a rep reading a sentence should see
    the same names they see everywhere else rather than wording invented here.
    """
    return [name.replace("_", " ") for name in names]


def _written_list(items: Sequence[str]) -> str:
    """Join things into the list a person would write: "a", "a and b", "a, b and c".

    Written out again here rather than shared with the pre-flight screen's copy: the two
    are the same three lines by coincidence, and a sentence built for one reader is not a
    reason to tie two layers together.

    Never called with nothing, because every caller has already found something to say.
    """
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
