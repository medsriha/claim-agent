"""The four things that can be recommended for a claim line, and who gets to choose.

Every claim line ends in one of four recommendations and nothing else (FR-1.14):
pay it, ask the merchant for something, refuse it, or hand it to a person. Each is
a **proposal to a rep**. None of them takes effect on its own, and no amount of
confidence changes that (FR-1.17, FR-3.1).

The choice is the agent's. It weighs the evidence and the assessments and says what
it would do, including refusing a claim outright — that is a judgement, and
judgement is what the agent is for.

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
from claim_agent.domain.reimbursement import AmountDerivation
from claim_agent.policy import Policy


class Recommendation(StrEnum):
    """What the system proposes doing about one claim line (FR-1.14).

    `APPROVE` proposes paying the merchant, and is the only one that carries an
    amount. `REQUEST_INFO` proposes going back to them for something specific — the
    outcome whenever a piece of evidence is missing or unusable (FR-1.6).
    `DENY` proposes refusing the claim. `ESCALATE` proposes handing it to a person
    without a suggested answer, which is where every uncertainty and every failure
    ends up (FR-1.15, FR-1.16, NFR-4).

    There is deliberately no fifth value. A run that cannot reach one of these four
    has failed, and failing means escalating.
    """

    APPROVE = "approve"
    REQUEST_INFO = "request_info"
    DENY = "deny"
    ESCALATE = "escalate"


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
    `NOT_CONFIDENT_ENOUGH` means the weakest assessment fell below the threshold in
    the policy file (FR-1.15). `BUDGET_EXHAUSTED` means the run ran out of steps
    before it could finish, and whatever it established is carried forward rather
    than being thrown away (FR-1.16). `PRODUCT_NOT_PRICEABLE` means the damaged
    product could not be tied to exactly one line on the order, so there is no
    price to pay from (FR-1.13, FR-1a.2).

    `CLAIM_CAP_EXCEEDED` is the odd one out, and worth understanding. Every other
    reason here is decided from one product's own evidence. This one is decided from
    the claim as a whole: the products being recommended for payment come to more
    than the cap between them. It cannot be worked out per product, because three
    products at fifty each are each fine and together are not — and a cap that only
    ever looked at one product at a time could be got round by splitting a claim into
    more of them, which is exactly what FR-1.20 warns about. So it is applied once,
    after every product has been investigated on its own, and it is the single place
    in this system where one product's outcome depends on what else was claimed
    beside it. Nothing is trimmed to fit: the claim goes to a person, who decides
    what to pay.
    """

    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    EVIDENCE_UNREADABLE = "evidence_unreadable"
    INVESTIGATION_INCOMPLETE = "investigation_incomplete"
    CLAIM_CAP_EXCEEDED = "claim_cap_exceeded"
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
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    recommendation: Recommendation
    recommended_by_agent: Recommendation
    overrides: tuple[OverrideReason, ...] = ()
    explanation: str

    @property
    def was_overridden(self) -> bool:
        """True when a rule stepped in and withheld what the investigation recommended.

        Not the same as the recommendation having changed, and the difference is
        real: an investigation that already recommended handing the line to a
        person, on a line a rule would also have escalated, has a rule recorded
        here while `recommendation` and `recommended_by_agent` are identical. The
        rule did apply; it simply agreed. Compare the two fields directly if what
        you want to know is whether the answer moved.
        """
        return bool(self.overrides)


_WITHHELD_RECOMMENDATION: dict[OverrideReason, Recommendation] = {
    OverrideReason.BUDGET_EXHAUSTED: Recommendation.ESCALATE,
    OverrideReason.EVIDENCE_UNREADABLE: Recommendation.ESCALATE,
    OverrideReason.INVESTIGATION_INCOMPLETE: Recommendation.ESCALATE,
    OverrideReason.CLAIM_CAP_EXCEEDED: Recommendation.ESCALATE,
    OverrideReason.EVIDENCE_INCOMPLETE: Recommendation.REQUEST_INFO,
    OverrideReason.NOT_CONFIDENT_ENOUGH: Recommendation.ESCALATE,
    OverrideReason.PRODUCT_NOT_PRICEABLE: Recommendation.ESCALATE,
}
"""What each rule leaves in place of the payment it withheld.

Only two of the four recommendations can be reached this way. A rule can send the
claim back to the merchant for something specific, or hand it to a person; no rule
can pay, and no rule refuses a claim outright, because refusing is a judgement
about the merits and these are not judgements (FR-1.14).
"""

_RECOMMENDATION_IN_WORDS: dict[Recommendation, str] = {
    Recommendation.APPROVE: "paying this line",
    Recommendation.REQUEST_INFO: "going back to the merchant",
    Recommendation.DENY: "refusing this line",
    Recommendation.ESCALATE: "handing this line to a person",
}
"""Each recommendation as a rep would say it, for the sentence that explains the outcome."""


def decide_outcome(
    recommended_by_agent: Recommendation,
    *,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    line: ClaimLine,
    amount: AmountDerivation | None,
    policy: Policy,
    budget_exhausted: bool = False,
) -> OutcomeDecision:
    """Settle what is recommended for one claim line, after the rules have had their say.

    The investigation has already decided what it would do. This applies the handful of
    requirements that are written as rules rather than judgements, and it can only ever
    push in one direction: **it can withhold a payment the requirements forbid, and it
    can never move a recommendation towards paying.** A refusal and a hand-off to a
    person are the investigation's own to make and are left alone (FR-1.14).

    Two rules apply whatever was recommended, because neither is about the merits of the
    claim. A run that used up its step budget did not finish, so it has not established a
    payment *or* a refusal, and it goes to a person with whatever it did establish
    (FR-1.16). Evidence we could not read ourselves is our failure, and it goes to a
    person too — never back to the merchant, who can do nothing about our download
    (FR-1.7, NFR-4).

    The rest apply only to a recommendation of payment: evidence that is not all in hand
    (FR-1.6), a question answered no (FR-1.12), a question never answered at all,
    confidence under the threshold in the claim policy (FR-1.15), and a product that
    cannot be tied to one price (FR-1.13, FR-1a.2).

    Those middle two look alike and are not. A question answered no is a finding about
    the claim, and the merchant is the one who can act on it. A question left unanswered
    is a finding about *us* — the run stopped early, or lost its way — and it goes to a
    person, because there is nothing to ask the merchant for.

    **Every rule that applies is reported, not just the first.** A rep should see
    everything that was wrong with the line rather than fixing one thing and discovering
    the next, so the checks all run and their reasons are collected — the same habit the
    pre-flight screen has. Where several apply, the recommendation left standing is the
    most cautious of them: handing the claim to a person beats going back to the
    merchant, because a person can do either and the merchant cannot (NFR-4).

    Nothing about the other claim lines in the claim reaches this function. That is what
    makes a line reach the same recommendation whether it was claimed alone or alongside
    five others (FR-1b.4), and there is no clock, no network and no model here either, so
    the same line always decides the same way (NFR-1).

    Args:
        recommended_by_agent: What the investigation concluded. Kept on the result
            whether or not it survives, so a rep can see that the rules disagreed with
            the investigation rather than only seeing the outcome (NFR-3).
        evidence: What was found for each of the four pieces of evidence. A piece not
            mentioned at all counts as not having it.
        assessments: The four judgements made once the evidence was in. May be short or
            empty, which is an unfinished investigation rather than a clean one.
        line: The claim line, read for whether its product matched exactly one line on
            the order. An unmatched product has no single price to pay from.
        amount: What a payment would come to, as worked out by code. `None` when no
            amount was worked out at all, which is never a reason to pay.
        policy: Read for the lowest confidence a payment may be recommended on
            (FR-0.7, NFR-7).
        budget_exhausted: True when the run ran out of steps before it could finish.

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

    if recommended_by_agent is Recommendation.APPROVE:
        withheld.extend(
            _reasons_to_withhold_approval(
                evidence=evidence,
                assessments=assessments,
                line=line,
                amount=amount,
                policy=policy,
            )
        )

    if not withheld:
        return OutcomeDecision(
            recommendation=recommended_by_agent,
            recommended_by_agent=recommended_by_agent,
            explanation=(
                "The investigation recommends "
                f"{_RECOMMENDATION_IN_WORDS[recommended_by_agent]}, and none of the "
                "rules changed that."
            ),
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
    line: ClaimLine,
    amount: AmountDerivation | None,
    policy: Policy,
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
                OverrideReason.EVIDENCE_INCOMPLETE,
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

    weakest = lowest_confidence(assessments)
    if weakest is None or weakest < policy.min_assessment_confidence:
        withheld.append((OverrideReason.NOT_CONFIDENT_ENOUGH, _confidence_clause(weakest, policy)))

    not_priceable = _why_not_priceable(line, amount)
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
    """Say how sure the investigation's weakest answer was, against how sure it had to be.

    Both figures are written to two decimal places, so the same claim reads identically
    every time rather than depending on how a fraction happens to print (NFR-1).

    Neither wording carries a comma of its own. Several of these clauses are read out in
    one sentence, and a comma inside one of them would look like the next item in the
    list.
    """
    required = f"{policy.min_assessment_confidence:.2f}"
    if weakest is None:
        return f"nothing was assessed and so nothing met the {required} confidence needed"
    return f"its least confident answer was {weakest:.2f} against the {required} needed"


def _why_not_priceable(line: ClaimLine, amount: AmountDerivation | None) -> str | None:
    """Say why no payment can be worked out for this line, or `None` if one can.

    A product that matched no order line, or several, has no single price to pay from,
    and the requirements are explicit that the system must ask rather than pick the
    likeliest candidate (FR-1.13, FR-1a.2). An amount of nothing is not payable either,
    however it arose, and the reason it arose is worth stating: a rep can chase a missing
    invoice, and nobody has ever said what a free item does to a claim.
    """
    if not line.is_matched:
        if line.match is MatchOutcome.NOT_ON_ORDER:
            return "the damaged product is not on the order"
        return (
            "the damaged product matches more than one line on the order, "
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
    return "the invoice prices the damaged product at nothing"


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
    if Recommendation.ESCALATE in left_standing:
        return Recommendation.ESCALATE
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
