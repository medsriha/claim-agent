"""Layer 1b — look into one damaged product and hand a representative a decision.

A merchant opens one support case, but that case can cover several damaged products.
Each of those products is a **claim line**, and this file investigates exactly one of
them: it runs the tool-use loop over the claim, settles what the evidence shows, works
out what a payment would come to, applies the handful of requirements that are rules
rather than judgements, and finishes the email a representative would send (FR-1b.1).

**The run sees the whole claim and answers for one product** (FR-1b.2). It is shown the
merchant's entire account, every image, every line on the order and the names of the
other products being claimed for, because a photograph showing two broken items matters
to both of them and the description is the only account anybody has of what happened.
What should happen to the other products is somebody else's question.

**The same product reaches the same answer whether it was claimed alone or beside five
others** (FR-1b.4). Three things make that true rather than hoped for:

- the other products are put to the model in a fixed order, sorted by name, with the one
  fact about them that depends on how the claim was split — which photographs an earlier
  pass tied to each — left out, so the question this run is asked does not change when
  the same claim is divided differently or arrives in a different order;
- whether it can be told which product was damaged is judged against **the order's line
  items**, which are the same however the claim is split, and never against the other
  claim lines. That judgement was already made when the claim was split and travels on
  the claim line itself;
- the two pieces of code that settle the outcome and the figure are handed no
  information about the other products at all. Neither takes such an argument, and
  neither may be given one.

**Nothing here writes a figure.** The model says which products were damaged; a
deterministic function prices them from the invoice (FR-1.21). The only money in a
finished email is arithmetic a representative can check.

**Every failure ends in front of a person** (NFR-4). A run that used up its steps, a
model that could not be reached, an answer that would not fit the form, or an email the
checks refused all produce a finished write-up recommending that a person look at the
line, carrying everything that was established on the way. Nothing in here raises for a
failure that happened to a claim.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import BudgetLimit, BudgetSnapshot, RunBudget
from claim_agent.agent.email import finish_email
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import LedgerEntry, RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.loop import LoopOutcome, run_agent_pass
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import build_investigation_messages
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.agent.tools import investigation_tools
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, Assessment
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    SHARED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import Attachment, DraftedEmail, Invoice
from claim_agent.domain.outcome import OutcomeDecision, Recommendation, decide_outcome
from claim_agent.domain.reimbursement import AmountDerivation, compute_reimbursement
from claim_agent.errors import ModelOutputRejectedError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet

logger = get_logger(__name__)

CLOSING_REQUEST = (
    "Now give your conclusion for this one product: what each of the four pieces of "
    "evidence showed, your answers to the four questions if the evidence was all there, "
    "which products should be paid for, what you recommend, and the email that would go "
    "to the merchant."
)
"""What the run is asked once it has stopped looking at things.

The wording of the investigation itself lives with the other prompts. This one
sentence lives here because it belongs to this pass rather than to the wording of
the question, and because the loop takes it as an argument.
"""

_RECOMMENDATION_IN_WORDS: dict[Recommendation, str] = {
    Recommendation.APPROVE: "pay this product",
    Recommendation.REQUEST_INFO: "go back to the merchant",
    Recommendation.DENY: "refuse this product",
    Recommendation.ESCALATE: "hand this product to a person",
}
"""Each recommendation as a representative would say it, for the message on a screen.

Written out again here rather than shared with the sentence the rules produce. That
one explains a decision and this one narrates a run, and a phrase built for one
reader is not a reason to tie the two together.
"""

_NOTHING_ESTABLISHED = "Nothing was established about this piece of evidence."
"""What is recorded for a piece of evidence nobody reported on.

Every write-up shows all four, so that a representative sees what was found rather
than inferring it from silence (FR-2.2). A piece nobody looked at is already
treated as one we do not have, so saying so out loud changes no decision — it only
stops a gap in the report reading as a clean result.
"""


class LineInvestigation(BaseModel):
    """Everything one damaged product's investigation established, ready to be reported on.

    This is the whole handoff for one claim line: what was found, what was judged,
    what stands, what it would cost, what worries the run had, the email that would
    go out, and the record of how it was all reached. A representative deciding on
    this line should need nothing else, and should be able to answer "why this
    amount?" and "why was this escalated?" from here alone (NFR-3).

    Frozen, because it is the account of something that has already happened.

    Fields:
        line: The one product this is about, with how it matched the order.
        evidence: What was found for each of the four pieces of evidence a claim
            needs, always all four and always in the same order. The invoice, the
            customer confirmation and the outer packaging were settled once for the
            whole claim and every product on the claim is handed the same answer
            (FR-1a.3); the photographs of the damage are this product's own.
        assessments: The four questions the run answered once the evidence was in
            hand, in the fixed reporting order. **This can be shorter than four**,
            and a question missing from it was never answered rather than answered
            no — an incomplete investigation, which is a different thing from a
            finding against the claim, and the two must never be confused.
        outcome: What is recommended for this line, what the investigation itself
            had recommended, and which rules stepped in between the two.
        amount: What a payment would come to, worked out from the invoice by code,
            with the working that makes it checkable (FR-1.21, FR-2.4). Always
            present, even when it comes to nothing, because "nothing, and here is
            why" is an answer a representative can act on.
        concerns: Anything weak, conflicting or uncertain, in the run's own words,
            followed by anything the code has to add — an ambiguity it reported, a
            disagreement with what the claim had already settled, the reason it gave
            up, or an email that was refused. Silence here is treated as a defect
            rather than a clean result (FR-2.5).
        drafted_email: The exact wording that would go to the merchant, unsent and
            marked as such (FR-1.17). It is `None` when there is nothing to send:
            the run gave up before writing anything, or what it wrote was refused.
            The line then goes to a person, who is the one who decides what the
            merchant is told.
        ledger: Every step the run took, in order, including the ones that failed
            (NFR-3, NFR-5).
        budget: What the run spent and which of its limits it reached, so an
            escalation can be explained without anyone reading logs.
        conclusion: The model's own answer, exactly as it gave it, or `None` when
            the run never reached one. Keep the two apart when reading this: the
            fields above are what stands after the claim's settled evidence was
            merged in and the rules ran, and this is what the investigation itself
            said. Where they differ, `outcome` says which rule made the difference.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    line: ClaimLine
    evidence: tuple[EvidenceFinding, ...]
    assessments: tuple[Assessment, ...]
    outcome: OutcomeDecision
    amount: AmountDerivation
    concerns: tuple[str, ...]
    drafted_email: DraftedEmail | None
    ledger: tuple[LedgerEntry, ...]
    budget: BudgetSnapshot
    conclusion: InvestigationConclusion | None

    @property
    def confidence(self) -> float | None:
        """How sure the investigation was of its own recommendation, from 0 to 1.

        `None` means the run never reached a conclusion, which must not be read as
        low confidence: nothing was assessed, so there is nothing to be sure about.

        Read off the conclusion rather than stored beside it, so there is one
        number rather than two that could disagree. It is a self-report and nothing
        in this system checks it against what turned out to be true.
        """
        return self.conclusion.confidence if self.conclusion is not None else None


async def investigate_line(
    *,
    line: ClaimLine,
    record: CaseRecord,
    context: ClaimContext,
    attachments: Sequence[Attachment],
    invoice: Invoice | None,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    cache: ObservationCache,
    events: EventStream,
    policy: Policy,
    shared_evidence: Sequence[EvidenceFinding] = (),
    siblings: Sequence[ClaimLine] = (),
    precedent: PrecedentSet | None = None,
) -> LineInvestigation:
    """Investigate one damaged product and produce everything a representative needs.

    One run of the tool-use loop, and then the rules. The run chooses for itself which
    photographs to look at and what to ask about them (FR-1.1); what it comes back with
    is then settled in a fixed order that never depends on the model:

    1. the evidence the claim had already settled is merged with this run's own read of
       the photographs of *its* product (FR-1a.3);
    2. the figure is worked out in code from the products the run says were damaged,
       priced against the invoice — never from anything the model wrote (FR-1.21);
    3. the requirements that are written as rules are applied to what the run
       recommended. They can withhold a payment the rules forbid and can never move a
       recommendation towards paying (FR-1.6, FR-1.12, FR-1.15, FR-1.16);
    4. the email is finished, with the real figure written into it.

    Never raises for anything that can happen to a claim. A run that gave up, and an
    email that was refused, both come back as a finished write-up recommending that a
    person look at the line, carrying whatever was established (FR-1.16, NFR-4).

    Args:
        line: The one product this run answers for. Whether it could be told apart from
            everything else on the order was decided when the claim was split, against
            the order's line items, and travels on this.
        record: What the pre-flight screen read — the case, the shipment and the order
            (FR-0.1). The case supplies the merchant's account, the address any email
            would go to, and the ids the tools read from.
        context: The facts the pre-flight screen worked out, so the run does not spend
            steps rediscovering them (FR-0.5).
        attachments: Every image on the claim, not only the ones tied to this product.
            An empty list is an ordinary answer and is put to the run as one.
        invoice: ShipBob's priced record of what the shipment held, generated once for
            the claim. `None` when it could not be got, which prices nothing and so
            leaves no payment to recommend — never a fallback to the order's prices.
        evidence: Reads the claim's images and prices the shipment. The only ShipBob
            client the run holds, and it can only read (FR-1.2).
        fetcher: Turns an image's address into the picture itself.
        structured: The model, constrained to answer on a form (NFR-2). Used both to
            draw the conclusion and to say what an image shows.
        chat: The model the run talks to, with the tools bound to it. Pass the same one
            the constrained asker wraps, so one model does the whole investigation.
        cache: The claim's memo of what images have already been looked at. Shared by
            every product on the claim, so no photograph is paid for twice (NFR-8).
        events: Where the run narrates itself while it works. Shared by the claim.
        policy: The thresholds this claim is judged by — the step allowance, the
            confidence a payment needs, the cap (FR-0.7, NFR-7). Read once here, so a
            line being investigated finishes on the values it started with.
        shared_evidence: What was settled once for the whole claim about the invoice,
            the customer confirmation and the outer packaging (FR-1a.3). Empty means
            nothing has been settled, and then this run's own read of them is used.
        siblings: The claim's other products. Shown to the run by name as context and
            nothing more, so it can read a photograph that covers two of them
            (FR-1b.2). Empty for a claim covering one product.
        precedent: The closed claims most like this product, looked up before the run
            started rather than searched for by the model (FR-S.6). This is what lets a
            product be judged the way comparable products actually were, instead of from
            the evidence alone every time. `None` means nobody looked, which is different
            from having looked and found none, and shows no section at all (FR-S.13).

    Returns:
        The finished investigation of this one line: the evidence, the judgements, the
        recommendation that stands, the figure and its working, the concerns, the
        drafted email, and the record of how it was reached.
    """
    case = record.case
    # One budget and one record per run, built here rather than taken as arguments, so
    # two products can never end up sharing an allowance: a claim with four products has
    # four budgets, not one split between them (FR-1.3).
    budget = RunBudget(policy)
    ledger = RunLedger()

    await events.emit(
        EventKind.LINE_STARTED,
        f"Looking into {line.product_name}.",
        claim_line_id=line.claim_line_id,
        product=line.product_name,
    )

    outcome = await run_agent_pass(
        opening_messages=build_investigation_messages(
            case=case,
            order=record.order,
            attachments=attachments,
            context=context,
            claim_line=line,
            other_lines=_the_other_products(siblings, line),
            shared_evidence=shared_evidence,
            precedent=precedent,
        ),
        tools=investigation_tools(
            case_id=case.case_id,
            shipment_id=case.shipment_id,
            user_id=case.user_id,
            evidence=evidence,
            fetcher=fetcher,
            model=structured,
            cache=cache,
            budget=budget,
            ledger=ledger,
            events=events,
            policy=policy,
            claim_line_id=line.claim_line_id,
        ),
        concludes_with=InvestigationConclusion,
        closing_request=CLOSING_REQUEST,
        chat=chat,
        structured=structured,
        budget=budget,
        ledger=ledger,
        events=events,
        claim_line_id=line.claim_line_id,
    )

    investigated = _settle(
        outcome,
        line=line,
        shared_evidence=shared_evidence,
        invoice=invoice,
        policy=policy,
        contact_email=case.contact_email,
    )

    logger.info(
        "claim_line_investigated",
        case_id=case.case_id,
        claim_line_id=line.claim_line_id,
        recommendation=investigated.outcome.recommendation.value,
        recommended_by_agent=investigated.outcome.recommended_by_agent.value,
        gave_up=outcome.gave_up,
    )
    await events.emit(
        EventKind.LINE_FINISHED,
        f"Finished with {line.product_name}. The recommendation is to "
        f"{_RECOMMENDATION_IN_WORDS[investigated.outcome.recommendation]}.",
        claim_line_id=line.claim_line_id,
        recommendation=investigated.outcome.recommendation.value,
    )
    return investigated


def _settle(
    outcome: LoopOutcome[InvestigationConclusion],
    *,
    line: ClaimLine,
    shared_evidence: Sequence[EvidenceFinding],
    invoice: Invoice | None,
    policy: Policy,
    contact_email: str | None,
) -> LineInvestigation:
    """Turn what one run came back with into the write-up a representative reads.

    Everything from here on is arithmetic and rules: no model is asked anything, so the
    same run always settles the same way (NFR-1).

    There are three ways out. A run that never reached a conclusion goes to a person
    with whatever was established. A run that concluded has its figure worked out, the
    rules applied, and its email finished. And an email the checks refuse also goes to a
    person, because a representative cannot be shown wording that broke the rule about
    who writes figures (FR-1.21, NFR-4).
    """
    if outcome.answer is None:
        return _a_run_that_gave_up(
            outcome, line=line, shared=shared_evidence, invoice=invoice, policy=policy
        )

    conclusion = outcome.answer
    evidence = _what_the_evidence_shows(conclusion.evidence, shared_evidence)
    assessments = _questions_that_were_answered(conclusion.assessments)
    amount = compute_reimbursement(_damaged_products(conclusion), invoice=invoice, policy=policy)
    concerns = _concerns(conclusion, shared_evidence)

    decision = decide_outcome(
        conclusion.recommendation,
        evidence=evidence,
        assessments=assessments,
        line=line,
        amount=amount,
        policy=policy,
    )

    try:
        drafted = finish_email(
            conclusion,
            recommendation=decision.recommendation,
            amount=amount,
            contact_email=contact_email,
        )
    except ModelOutputRejectedError as refused:
        # The wording cannot be shown to anyone, so the investigation's own
        # recommendation is set aside and a person takes the line. That is the one
        # direction code may move a recommendation in (NFR-4); what the run concluded
        # is kept below, so a representative can still read it.
        logger.warning(
            "drafted_email_refused",
            claim_line_id=line.claim_line_id,
            recommendation=decision.recommendation.value,
        )
        return LineInvestigation(
            line=line,
            evidence=evidence,
            assessments=assessments,
            outcome=_hand_it_to_a_person(
                evidence=evidence,
                assessments=assessments,
                line=line,
                amount=amount,
                policy=policy,
            ),
            amount=amount,
            concerns=_also(concerns, refused.message),
            drafted_email=None,
            ledger=outcome.ledger,
            budget=outcome.budget,
            conclusion=conclusion,
        )

    return LineInvestigation(
        line=line,
        evidence=evidence,
        assessments=assessments,
        outcome=decision,
        amount=amount,
        concerns=concerns,
        drafted_email=drafted,
        ledger=outcome.ledger,
        budget=outcome.budget,
        conclusion=conclusion,
    )


def _a_run_that_gave_up(
    outcome: LoopOutcome[InvestigationConclusion],
    *,
    line: ClaimLine,
    shared: Sequence[EvidenceFinding],
    invoice: Invoice | None,
    policy: Policy,
) -> LineInvestigation:
    """Write up a run that stopped before it could conclude (FR-1.16, NFR-4).

    The point of this is that a representative is not handed an empty result. Whatever
    the claim had already settled about the invoice, the customer confirmation and the
    outer packaging is still true, the record of what the run managed to do is still
    worth reading, and the reason it stopped is put among the concerns in the run's own
    plain words.

    Nothing was recommended by the investigation, so nothing is claimed on its behalf:
    the line goes to a person, and the conclusion is recorded as absent rather than
    invented. There is no email, because nobody has decided what the merchant should be
    told — that is now the representative's to decide.
    """
    evidence = _what_the_evidence_shows((), shared)
    amount = compute_reimbursement((), invoice=invoice, policy=policy)
    return LineInvestigation(
        line=line,
        evidence=evidence,
        assessments=(),
        outcome=_hand_it_to_a_person(
            evidence=evidence,
            assessments=(),
            line=line,
            amount=amount,
            policy=policy,
            budget_exhausted=_ran_out_of_steps(outcome),
        ),
        amount=amount,
        concerns=_also((), outcome.reason),
        drafted_email=None,
        ledger=outcome.ledger,
        budget=outcome.budget,
        conclusion=None,
    )


def _hand_it_to_a_person(
    *,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    line: ClaimLine,
    amount: AmountDerivation,
    policy: Policy,
    budget_exhausted: bool = False,
) -> OutcomeDecision:
    """Settle a line that has to go to a person, still through the ordinary rules.

    Handing a line to a person is proposed rather than imposed here, and the rules are
    asked about it exactly as they are asked about anything else. They can only ever be
    more cautious than that, so the result is always an escalation — and it arrives
    carrying whatever else the rules found wrong with the line, which is what a
    representative needs to see (NFR-3).

    Escalating is proposed as the run's *own* recommendation here, rather than the
    recommendation being carried over from what the run actually concluded. That is
    deliberate and worth being careful about: passing the run's own answer through
    would let the rules approve a line whose email had just been thrown away, leaving a
    payment recommended with nothing to send. What the run concluded is not lost — it
    is kept whole on the line's `conclusion`, which is where a representative can read
    it (NFR-3).
    """
    return decide_outcome(
        Recommendation.ESCALATE,
        evidence=evidence,
        assessments=assessments,
        line=line,
        amount=amount,
        policy=policy,
        budget_exhausted=budget_exhausted,
    )


def _ran_out_of_steps(outcome: LoopOutcome[InvestigationConclusion]) -> bool:
    """Say whether the run stopped without concluding because its steps ran out (FR-1.16).

    Both halves matter. A run that spent its last step and *did* conclude has finished
    its work, and escalating it would make the answer depend on how big the allowance
    happened to be rather than on the claim. A run that stopped early for some other
    reason — a model that could not be reached, an answer that would not fit the form —
    still goes to a person, but not for this reason, and saying so would send whoever
    reads the write-up looking in the wrong place.
    """
    return outcome.gave_up and BudgetLimit.STEPS in outcome.budget.limits_reached


def _the_other_products(siblings: Sequence[ClaimLine], line: ClaimLine) -> tuple[ClaimLine, ...]:
    """The claim's other products, in a fixed order, with nothing that could sway this run.

    This is the load-bearing part of "a product reaches the same answer whether it was
    claimed alone or beside five others" (FR-1b.4). The run has to be told what else is
    being claimed for, because one photograph can show two broken items (FR-1b.2) — so
    the guarantee cannot come from hiding them. It comes from making what is shown fixed:

    - **This product is never among its own siblings**, so a caller handing over the
      whole claim asks the same question as one handing over only the others.
    - **They are sorted by name**, so the order the products happened to arrive in
      cannot change a word of the question.
    - **Which photographs an earlier pass tied to each of them is dropped**, because
      that is the one fact about another product that depends on how the claim was
      divided. Everything else — its name, how many were claimed, whether it matched the
      order — is worked out against the order's line items, which are the same however
      the claim is split, so it cannot make this run answer differently and is left as
      it is rather than blanked to something that would be untrue if it were ever shown.

    Returns them as claim lines because that is what the question is built from. Only
    their names are put to the model today.
    """
    others = [other for other in siblings if other.claim_line_id != line.claim_line_id]
    in_order = sorted(others, key=lambda other: (other.product_name, other.claim_line_id))
    return tuple(other.model_copy(update={"damage_attachment_ids": ()}) for other in in_order)


def _what_the_evidence_shows(
    reported: Sequence[EvidenceJudgement], shared: Sequence[EvidenceFinding]
) -> tuple[EvidenceFinding, ...]:
    """Merge what the claim settled once with what this run found about its own photographs.

    Three of the four pieces of evidence — the invoice, the customer confirmation and
    the photograph of the outer box — describe the parcel rather than any one product,
    so they are settled once for the whole claim and every product is handed the same
    answer (FR-1a.3). That is a cost control, and more importantly a consistency
    guarantee: two products on one claim can never disagree about whether the box was
    photographed. So what was settled wins over this run's own read of them, and where
    the two differ the disagreement is reported as a concern rather than dropped.

    Photographs of the damage are this run's own, because they are about its product.

    All four come back, in the fixed reporting order, so a representative sees what was
    found rather than inferring it from silence (FR-2.2). A piece nobody reported on is
    recorded as one we do not have — which is exactly how the rules already treat a
    piece nobody looked for, so writing it down changes no decision.
    """
    this_run = {judgement.kind: _as_a_finding(judgement) for judgement in reported}
    settled_once = {finding.kind: finding for finding in shared if finding.kind in SHARED_EVIDENCE}
    found = {**this_run, **settled_once}
    return tuple(found.get(kind, _nothing_found_about(kind)) for kind in REQUIRED_EVIDENCE)


def _as_a_finding(judgement: EvidenceJudgement) -> EvidenceFinding:
    """Turn the form the model filled in about one piece of evidence into a finding.

    The same facts in the shape the rest of the system reads. Nothing is decided here:
    what the model said the evidence was is what is recorded, including that it was
    missing or that it arrived unusable.
    """
    return EvidenceFinding(
        kind=judgement.kind,
        state=judgement.state,
        observed=judgement.observed,
        attachment_id=judgement.attachment_id,
        problem=judgement.problem,
    )


def _nothing_found_about(kind: EvidenceKind) -> EvidenceFinding:
    """Record that one of the four pieces of evidence was never reported on.

    Written down as evidence we do not have. The alternative is leaving it out of the
    write-up altogether, and a gap that has to be noticed reads far too much like a
    piece of evidence that was fine.
    """
    return EvidenceFinding(kind=kind, state=EvidenceState.MISSING, observed=_NOTHING_ESTABLISHED)


def _questions_that_were_answered(
    judgements: Sequence[AssessmentJudgement],
) -> tuple[Assessment, ...]:
    """The four questions this run actually answered, in the fixed reporting order.

    Deliberately short when the run answered fewer than four. A question nobody answered
    has no answer to record: writing one down would have to say it was answered no,
    which is a finding against the claim rather than an unfinished investigation, and
    the rules treat those two very differently — one goes back to the merchant, the
    other goes to a person.

    A question answered twice keeps the later answer, so a revision can replace one
    judgement without the set being rebuilt.
    """
    answered = {judgement.name: _as_an_assessment(judgement) for judgement in judgements}
    return tuple(answered[name] for name in REQUIRED_ASSESSMENTS if name in answered)


def _as_an_assessment(judgement: AssessmentJudgement) -> Assessment:
    """Turn the form the model filled in about one question into a judgement on the claim."""
    return Assessment(
        name=judgement.name,
        passed=judgement.passed,
        reasoning=judgement.reasoning,
        confidence=judgement.confidence,
        attachment_ids=judgement.attachment_ids,
    )


def _damaged_products(conclusion: InvestigationConclusion) -> tuple[ClaimedProduct, ...]:
    """The products the run says were damaged, in the shape the arithmetic prices.

    This is the whole of what the model contributes to the figure: which products, and
    how many of each. There is no price here and there is nowhere to put one — the
    prices come from the invoice (FR-1.21).
    """
    return tuple(
        ClaimedProduct(name=item.product_name, quantity=item.quantity, sku=item.sku)
        for item in conclusion.damaged_items
    )


def _concerns(
    conclusion: InvestigationConclusion, shared: Sequence[EvidenceFinding]
) -> tuple[str, ...]:
    """Everything a reviewer should know that does not fit anywhere else (FR-2.5).

    The run's own worries come first, in its own words and its own order. Then two
    things the code adds because the run cannot: an ambiguity it flagged about which
    product was damaged, which decides whether anything can be priced at all (FR-1.13),
    and any place where its read of the shared evidence differs from what the claim had
    already settled — because that judgement is set aside, and a judgement set aside
    quietly is a judgement nobody can argue with (NFR-3).

    Anything said twice is kept once, in the position it was first said.
    """
    return _also(
        conclusion.concerns,
        _the_ambiguity(conclusion),
        *_where_this_run_disagreed(conclusion, shared),
    )


def _the_ambiguity(conclusion: InvestigationConclusion) -> str | None:
    """Say what the run could not tell apart, or `None` if it could tell (FR-1.13).

    Orders carry similar products at different prices, and a run that cannot say which
    one was damaged must ask rather than pick the likelier candidate. A representative
    who is told exactly what is unclear settles it in seconds.
    """
    if not conclusion.is_ambiguous:
        return None
    if conclusion.ambiguity is None:
        return "The investigation could not tell which product on the order was damaged."
    return (
        "The investigation could not tell which product on the order was damaged: "
        f"{conclusion.ambiguity}"
    )


def _where_this_run_disagreed(
    conclusion: InvestigationConclusion, shared: Sequence[EvidenceFinding]
) -> tuple[str, ...]:
    """Name every piece of shared evidence this run read differently from the claim.

    The claim's own answer stands, so that two products on one claim are never judged
    against different readings of the same photograph (FR-1a.3). Saying so is what
    stops that being a silent overrule.
    """
    settled_once = {finding.kind: finding for finding in shared if finding.kind in SHARED_EVIDENCE}
    this_run = {judgement.kind: judgement for judgement in conclusion.evidence}
    return tuple(
        f"This run read the {kind.value.replace('_', ' ')} as "
        f"{this_run[kind].state.value} while the claim had settled it as "
        f"{settled_once[kind].state.value}. The claim's answer stands, so every product "
        "on it is judged the same way."
        for kind in REQUIRED_EVIDENCE
        if kind in settled_once
        and kind in this_run
        and this_run[kind].state is not settled_once[kind].state
    )


def _also(concerns: Sequence[str], *added: str | None) -> tuple[str, ...]:
    """Add to a list of concerns, keeping the order and dropping repeats.

    Nothing empty is added, and nothing is added twice: a run that already said what the
    code is about to say should not have it said again underneath.
    """
    kept = [*concerns, *(one for one in added if one)]
    return tuple(dict.fromkeys(kept))
