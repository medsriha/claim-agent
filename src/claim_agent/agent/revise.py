"""Layer R — reworking one product's report after a representative sent it back.

A representative reads a report and finds a fault in it: the photograph of the box is really
a photograph of the product, the amount looks wrong, the merchant already sent the thing we
are asking for. They say so in their own words, and this is what happens next.

**It is the same agent, not a second one** (FR-R.1). The tools are the same, the answer form
is the same form with three fields added, and the rules that settle the answer afterwards are
the identical function the first pass used. Two agents would need two copies of every rule,
and any drift between them would surface as a representative's correction quietly changing
how a rule is applied.

**It starts from the work already done, not from zero** (FR-R.2). The run is handed the
report as it stands — every finding, every judgement, the figure and its working, the
concerns, and the merchant's email — along with every earlier round of this conversation and
the note that has just arrived. It does not split the claim again and it does not investigate
the other products.

**What was found before is put to it as a record, not as a position to defend** (FR-R.3).
That is a real weakness being managed rather than solved: an agent shown its own earlier
verdict tends to argue for it. Two things push back — the wording calls those findings
observations somebody wrote down, and the answer has to say what changed, which makes an
unchanged conclusion visible instead of quietly persistent (FR-R.10).

**Findings the note does not touch are carried forward by code** (FR-R.5). Anything the
reworked answer leaves out is filled in from the earlier report before the rules run. Left to
the wording alone, an answer that mentioned only the one thing being corrected would have
turned the other three findings into "never established", and an approval would collapse
because somebody queried a sentence.

**Feedback cannot make a rule give way** (FR-R.8). The figure goes through the same capping
path as the first one and the same rules decide the final action, because it is literally the
same code. Where a note asks for something the rules forbid, the agent says so in its reply
rather than complying or ignoring it.

**Nothing here can send anything or pay anybody** (FR-R.6). The tools are the investigation's
tools, every one of which only reads, and no write tool exists in this package to be reached.

Nothing here raises for anything that can happen to a claim. A model that cannot be reached, a
run that used up its steps, and an answer that would not fit its form all come back as a
rework that did not happen, carrying a plain sentence saying why (NFR-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import LineInvestigation, settle_conclusion
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.loop import run_agent_pass
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import (
    EarlierExchange,
    build_claim_revision_messages,
    build_revision_messages,
    build_screening_revision_messages,
)
from claim_agent.agent.run import invoice_for_claim
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    EvidenceJudgement,
    RevisedClaimReport,
    RevisionConclusion,
)
from claim_agent.agent.tools import investigation_tools
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Attachment, DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import AmountDerivation
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet

logger = get_logger(__name__)

CLOSING_REQUEST = (
    "Now give the reworked report for this one product: all four pieces of evidence, the "
    "four questions where the evidence is there, what should be paid for, your next action, "
    "the merchant email where that action addresses them, what you changed, what you left "
    "alone, and your reply to the representative."
)
"""What the run is asked once it has stopped looking at things.

The wording of the rework itself lives with the other prompts. This one sentence lives here
because it belongs to this pass rather than to the wording of the question, and because the
loop takes it as an argument.
"""

_COULD_NOT_REWORK = (
    "This report could not be reworked, so nothing in it has changed. Send it back again to "
    "try once more, or decide on it as it stands."
)
"""What a representative is told when the run did not reach an answer.

Said in full rather than left to a screen to phrase, and paired with the run's own reason for
stopping, so the representative is told both what happened and what they can do about it
(NFR-4).
"""


class ReportUnderReview(BaseModel):
    """The report a representative sent back, in the parts a rework needs (FR-R.2).

    Deliberately not the stored report itself. What a report holds is a matter for the report
    layer; what an agent is shown is a matter for this one, and keeping the two apart is what
    stops a field being added to a report and silently appearing in a prompt.

    Fields:
        line: The one damaged product this report is about.
        context: The facts the deterministic screen worked out before anything expensive ran,
            including what a representative has corrected for this merchant before.
        attachments: Every image on the claim, so a photograph can be looked at again where
            the note points at one (FR-R.4).
        recommendation: What the report currently recommends.
        amount: What the report currently says a payment would come to, with its working.
        evidence: What the report currently records about each of the four pieces of
            evidence. Both shown to the run and used to fill in anything its answer leaves
            out (FR-R.5).
        assessments: The report's current answers to the four questions. Can be fewer than
            four: a question nobody answered is an unfinished investigation rather than a
            finding against the claim, and the two must not be confused.
        concerns: What the report currently says is worrying.
        drafted_email: The wording that would currently go to the merchant, or `None` — a
            report asking a representative to clarify something never carries one.
        conversation: Every earlier round of this report going back and forth, oldest first.
            Empty on a first rework. Carrying it is what stops a later correction undoing an
            earlier one (FR-R.12).
        siblings: The claim's other damaged products. Shown by name as context, and named
            again if the note turns out to be about evidence they share (FR-R.1a).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    line: ClaimLine
    context: ClaimContext
    attachments: tuple[Attachment, ...] = ()
    recommendation: Recommendation
    amount: AmountDerivation
    evidence: tuple[EvidenceFinding, ...] = ()
    assessments: tuple[Assessment, ...] = ()
    concerns: tuple[str, ...] = ()
    drafted_email: DraftedEmail | None = None
    conversation: tuple[EarlierExchange, ...] = ()
    siblings: tuple[ClaimLine, ...] = ()


class Reply(BaseModel):
    """What the agent says back to a representative, whatever kind of report it was.

    Every rework answers in this shape, so a screen draws one conversation rather than one
    per kind of report. A rework that did not happen answers in it too: the reason it did not
    is what the representative is told, and that is an ordinary outcome to report rather than
    an error page (NFR-4).

    Frozen, because it is the account of something that has already happened.

    Fields:
        reply: What the agent says back, in plain words, written to the representative. Where
            the rework did not happen, this is the reason it did not. Where they asked for
            something the rules forbid, this is where it says so (FR-R.8).
        changed: What was changed in response, one item each (FR-R.10).
        left_unchanged: What the message did not bear on and was carried forward as it was.
        needs_reply: Whether the agent asked a question it needs answered before this can be
            settled. It changes nothing about what is recommended; it says the conversation
            is waiting on a person.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reply: str
    changed: tuple[str, ...] = ()
    left_unchanged: tuple[str, ...] = ()
    needs_reply: bool = False

    @property
    def reworked(self) -> bool:
        """Whether anything about the report actually changed.

        Nothing did, at this level: a plain reply is a reply. The two kinds below say for
        themselves, from what they are carrying rather than from a flag beside it, so the
        answer can never contradict what is actually there.
        """
        return False


class LineRevision(Reply):
    """A reworked report for one damaged product (FR-R.9).

    `investigation` is the reworked findings, settled by the same rules the first pass ran
    through, or `None` when the run never reached an answer — in which case the report keeps
    everything it already said.
    """

    investigation: LineInvestigation | None = None

    @property
    def reworked(self) -> bool:
        """Whether the report was actually reworked.

        Worked out from whether there are findings rather than stored beside them, so the two
        can never contradict each other — the same reasoning that keeps a run's "gave up" off
        its record as a separate flag.
        """
        return self.investigation is not None


class ClaimRevision(Reply):
    """A reworked report about a whole claim rather than one product (FR-1a.4, FR-0.4).

    Two kinds of report name no product: a claim whose split was never settled, and a claim
    the quick checks turned away. Neither has anything investigated behind it, so neither can
    be given a recommendation to pay or an amount — there is nothing here that was ever
    priced.

    What may change differs between them, and the caller decides that rather than this shape:
    an unsettled split may have its ambiguity, its merchant requests and its email reworked,
    while a stopped claim may have only its email reworded, because its verdict came from
    fixed rules that feedback cannot overturn (FR-0.6, FR-R.8).

    Fields:
        recommendation: What the report should now recommend, or `None` to leave it. Never a
            payment: nothing here has been priced.
        ambiguity: What is still unclear, or `None` to leave it as it was.
        requested_details: What the merchant must still provide. Empty means nothing is
            needed from them any more, which is a real answer rather than an omission — so
            this is applied whenever anything else about the report changed.
        email: The merchant's email as it should now read, or `None` to leave the wording
            alone.
        reinvestigate: Whether the claim should be investigated again from its evidence. Set
            when what the representative said settles enough to make that worth doing — most
            often naming the damaged products — or when they asked for it outright. The
            caller runs the investigation; nothing here does.
    """

    recommendation: Recommendation | None = None
    ambiguity: str | None = None
    requested_details: tuple[str, ...] = ()
    email: DraftedEmail | None = None
    reinvestigate: bool = False

    @property
    def reworked(self) -> bool:
        """Whether anything about the report actually changed.

        A rework that only asks for a fresh investigation has changed nothing about the
        report *yet* — what changes it is the investigation, which the caller runs. Saying so
        keeps "the agent answered you" and "the report is different now" apart, which a
        representative reading an unchanged report needs.
        """
        return (
            self.recommendation is not None
            or self.ambiguity is not None
            or self.email is not None
            or bool(self.requested_details)
        )


async def rework_line(
    *,
    under_review: ReportUnderReview,
    feedback: str,
    record: CaseRecord,
    evidence_client: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    events: EventStream,
    policy: Policy,
    precedent: PrecedentSet | None = None,
) -> LineRevision:
    """Rework one product's report around what a representative said (FR-R.1 to FR-R.11).

    One run of the same tool-use loop the investigation uses, asked a question built from the
    report as it stands, and then settled by the same rules. The run chooses for itself
    whether it needs to look at anything again (FR-R.4); nothing here sequences it.

    Args:
        under_review: The report the representative sent back, in the parts a rework needs.
        feedback: What they said, in their own words, kept exactly as written. Paraphrasing
            it would change the question the run is answering.
        record: The case, its parcel and its order, re-read rather than remembered — the
            claim's contact address and the ids the tools read from all come from here.
        evidence_client: Reads the claim's images and prices the shipment. The only ShipBob
            client the run holds, and it can only read (FR-1.2, FR-R.6).
        fetcher: Turns an image's address into the picture itself.
        chat: The model to ask, with the tools bound to it per run.
        structured: The same model, wrapped so an answer either fits its form or fails
            (NFR-2).
        events: Where the rework narrates itself. A stream with nowhere to send them keeps
            them and sends them nowhere, which is what the route that answers in one piece
            passes.
        policy: The thresholds this claim is judged by (FR-0.7). The rework gets the same
            step allowance as an investigation: it is the same agent doing the same kind of
            work, and a second number would be one more provisional value to keep in step.
        precedent: The past claims most like this product. Shown again rather than withheld,
            because the figure may be reconsidered and it is judged against how comparable
            claims were actually settled (FR-R.7, FR-S.6). `None` means nobody looked.

    Returns:
        The reworked findings with what changed and a reply for the representative, or no
        findings and a reply saying why the rework did not happen. Never raises for anything
        that can happen to a claim.
    """
    line = under_review.line
    # One budget and one record per run, built here rather than taken as arguments, so a
    # rework can never end up sharing an allowance with the investigation that preceded it
    # (FR-1.3).
    budget = RunBudget(policy)
    ledger = RunLedger()
    cache = ObservationCache()

    await events.emit(
        EventKind.LINE_STARTED,
        f"Reworking {line.product_name} around what the representative said.",
        claim_line_id=line.claim_line_id,
        product=line.product_name,
    )

    invoice = await invoice_for_claim(record=record, evidence=evidence_client, cache=cache)

    outcome = await run_agent_pass(
        opening_messages=build_revision_messages(
            case=record.case,
            order=record.order,
            attachments=under_review.attachments,
            context=under_review.context,
            claim_line=line,
            recommendation=under_review.recommendation,
            amount=under_review.amount,
            evidence=under_review.evidence,
            assessments=under_review.assessments,
            concerns=under_review.concerns,
            drafted_email=under_review.drafted_email,
            feedback=feedback,
            conversation=under_review.conversation,
            other_lines=under_review.siblings,
            precedent=precedent,
        ),
        tools=investigation_tools(
            case_id=record.case.case_id,
            shipment_id=record.case.shipment_id,
            user_id=record.case.user_id,
            case=record.case,
            shipment=record.shipment,
            evidence=evidence_client,
            fetcher=fetcher,
            model=structured,
            cache=cache,
            budget=budget,
            ledger=ledger,
            events=events,
            policy=policy,
            claim_line_id=line.claim_line_id,
        ),
        concludes_with=RevisionConclusion,
        closing_request=CLOSING_REQUEST,
        chat=chat,
        structured=structured,
        budget=budget,
        ledger=ledger,
        events=events,
        claim_line_id=line.claim_line_id,
    )

    if outcome.answer is None:
        return await _a_rework_that_did_not_happen(outcome.reason, line=line, events=events)

    reworked = _carrying_forward(outcome.answer, under_review)
    investigated = settle_conclusion(
        replace(outcome, answer=reworked),
        line=line,
        # Nothing is pinned from the claim's shared evidence here, and that is the point of
        # a rework: the requirement's own example of feedback is a correction to one of the
        # shared findings, and pinning them would make it the one correction impossible to
        # make. What the earlier report established is merged into the answer instead, where
        # this run's own read of it wins (FR-R.5).
        shared_evidence=(),
        invoice=invoice,
        policy=policy,
        contact_email=record.case.contact_email,
        directed_by_representative=reworked.representative_directed_outcome,
    )
    investigated = _noting_the_other_products(
        investigated, answer=reworked, siblings=under_review.siblings
    )

    logger.info(
        "claim_line_reworked",
        case_id=record.case.case_id,
        claim_line_id=line.claim_line_id,
        recommendation=investigated.outcome.recommendation.value,
        changed=len(reworked.changed),
        needs_reply=reworked.needs_more_from_representative,
    )
    await events.emit(
        EventKind.LINE_FINISHED,
        f"Finished reworking {line.product_name}.",
        claim_line_id=line.claim_line_id,
        recommendation=investigated.outcome.recommendation.value,
    )

    return LineRevision(
        investigation=investigated,
        reply=reworked.reply_to_representative,
        changed=reworked.changed,
        left_unchanged=reworked.left_unchanged,
        needs_reply=reworked.needs_more_from_representative,
    )


async def _a_rework_that_did_not_happen(
    reason: str | None, *, line: ClaimLine, events: EventStream
) -> LineRevision:
    """Report a run that stopped before it could answer (FR-1.16, NFR-4).

    The representative is left with the report they already had and a plain sentence saying
    why it is unchanged, which is something they can act on: they can send it back again, or
    decide on it as it stands. The alternative is an error page, which loses the note as well
    as the rework.
    """
    logger.info("claim_line_rework_gave_up", claim_line_id=line.claim_line_id, reason=reason)
    await events.emit(
        EventKind.LINE_FINISHED,
        f"Could not rework {line.product_name}.",
        claim_line_id=line.claim_line_id,
        outcome="not_reworked",
    )
    said = f"{reason} {_COULD_NOT_REWORK}" if reason else _COULD_NOT_REWORK
    return LineRevision(investigation=None, reply=said)


def _carrying_forward(
    answer: RevisionConclusion, under_review: ReportUnderReview
) -> RevisionConclusion:
    """Fill in whatever the reworked answer left out, from the report it is reworking.

    This is FR-R.5 made structural rather than requested. The rules that settle an answer
    treat a piece of evidence nobody reported on as one we do not have, and a question nobody
    answered as an investigation that did not finish — both of which send a claim to a
    person. An answer that sensibly mentioned only the one thing being corrected would
    therefore have destroyed the rest of a sound report.

    The earlier findings go **before** this run's own, because both merges downstream keep
    the last entry for each kind and each question. So anything the rework spoke about wins,
    and anything it passed over survives.

    Returns:
        The same answer with the earlier report's evidence and judgements underneath it.
    """
    return answer.model_copy(
        update={
            "evidence": (
                *(_as_a_judgement(finding) for finding in under_review.evidence),
                *answer.evidence,
            ),
            "assessments": (
                *(_as_a_question_answered(answer_) for answer_ in under_review.assessments),
                *answer.assessments,
            ),
        }
    )


def _as_a_judgement(finding: EvidenceFinding) -> EvidenceJudgement:
    """Put a settled finding back into the form the model answers on.

    Only so it can be merged with a reworked answer on equal terms. Nothing is decided here
    and nothing is shown to the model in this shape — what the model reads is the wording
    built by the prompts.
    """
    return EvidenceJudgement(
        kind=finding.kind,
        state=finding.state,
        observed=finding.observed,
        attachment_id=finding.attachment_id,
        problem=finding.problem,
    )


def _as_a_question_answered(assessment: Assessment) -> AssessmentJudgement:
    """Put a settled answer to one of the four questions back into the model's form."""
    return AssessmentJudgement(
        name=assessment.name,
        passed=assessment.passed,
        reasoning=assessment.reasoning,
        attachment_ids=assessment.attachment_ids,
    )


def _noting_the_other_products(
    investigated: LineInvestigation,
    *,
    answer: RevisionConclusion,
    siblings: Sequence[ClaimLine],
) -> LineInvestigation:
    """Say when a correction bears on the claim's other products too (FR-R.1a, FR-1a.3).

    The invoice, the customer confirmation and the photograph of the outer box describe the
    parcel rather than any one product, so every product on the claim was handed the same
    answer about them. Correcting one of them ought to correct all of them.

    **This system says so and does not do it.** Reworking the siblings would be several more
    runs and several more reports going back for review, and that was not built. A concern
    naming them is the honest half: a representative can see that the other products still
    carry the old finding, instead of it being silently wrong.

    Nothing is added for a claim with one product, where there is nobody to propagate to.
    """
    if not answer.concerns_shared_evidence or not siblings:
        return investigated

    others = ", ".join(sorted(sibling.product_name for sibling in siblings))
    return investigated.model_copy(
        update={
            "concerns": (
                *investigated.concerns,
                "This correction is about evidence every product on the claim shares, so it "
                f"bears on {others} as well. Those reports still carry the earlier finding "
                "and have to be sent back separately.",
            )
        }
    )


async def rework_claim_report(
    *,
    case_record: CaseRecord,
    context: ClaimContext,
    attachments: Sequence[Attachment],
    ambiguity: str,
    candidate_lines: Sequence[ClaimLine],
    requested_details: Sequence[str],
    concerns: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange],
    structured: StructuredModel,
    events: EventStream,
) -> ClaimRevision:
    """Answer a representative who wrote back about a claim whose split was never settled.

    Nothing on such a claim was investigated: no photograph was judged and no product was
    priced, because nothing may be investigated while it is unclear which products are being
    claimed for (FR-1a.4). So the agent cannot approve anything here and cannot name an
    amount, however plainly it is asked to.

    **What it can do is answer, and ask for the claim to be looked at properly.** Where the
    representative has settled the split — usually by naming the damaged products — the answer
    sets `reinvestigate` and the caller runs a fresh investigation, which is the only honest
    route from a claim nobody could divide to a report somebody can approve. Where they asked
    a question or wanted different wording, the answer reworks what the merchant is being
    asked for and the email that asks them.

    **No tools, and one question.** A rework here has nothing to look at that would change its
    answer: the split was not unsettled for want of looking, and re-reading the photographs is
    what a fresh investigation is for. So this asks the model once, on a form, rather than
    running the tool-use loop — which also makes it fast enough to feel like a reply.

    Args:
        case_record: The case, its parcel and its order, re-read from ShipBob.
        context: The facts the deterministic screen worked out beforehand.
        attachments: Every image on the claim, named so the representative's answer can point
            at one.
        ambiguity: What the report currently says could not be established.
        candidate_lines: The products the report was choosing between, if it named any.
        requested_details: What the merchant is currently being asked for.
        concerns: What the report currently says is worrying.
        drafted_email: The wording currently going to the merchant, or `None`.
        feedback: What the representative said, in their own words.
        conversation: Every earlier round, oldest first (FR-R.12).
        structured: The model, constrained to answer on a form (NFR-2).
        events: Where the rework narrates itself.

    Returns:
        What to change about the report and what to say back, or nothing changed and a reply
        saying why. Never raises for anything that can happen to a claim.
    """
    await events.emit(
        EventKind.LINE_STARTED,
        "Answering the representative about this claim.",
    )

    try:
        answered = await structured.ask(
            RevisedClaimReport,
            build_claim_revision_messages(
                case=case_record.case,
                order=case_record.order,
                attachments=attachments,
                context=context,
                ambiguity=ambiguity,
                candidate_lines=candidate_lines,
                requested_details=requested_details,
                concerns=concerns,
                drafted_email=drafted_email,
                feedback=feedback,
                conversation=conversation,
            ),
        )
    except ClaimAgentError as failure:
        return _a_reply_that_could_not_be_written(failure, case_id=case_record.case.case_id)

    said = Reply(
        reply=answered.reply_to_representative,
        changed=answered.changed,
        left_unchanged=answered.left_unchanged,
        needs_reply=answered.needs_more_from_representative,
    )

    if not _anything_to_change(answered):
        # The agent answered without changing the report — because the message was a question,
        # or because it is asking for the claim to be investigated instead. Carrying the report
        # through untouched matters: filling in what the model left blank would drop a merchant
        # email nobody asked to drop.
        return ClaimRevision(**said.model_dump(), reinvestigate=answered.needs_fresh_investigation)

    email = _the_merchant_email(
        answered, contact_email=case_record.case.contact_email, existing=drafted_email
    )
    # A claim that names no product can only ever ask for something. It cannot recommend
    # paying, because nothing on it has been priced, and the rules that would withhold such a
    # recommendation are in a function that needs a product to run at all (FR-1a.4).
    asks_the_merchant = bool(answered.requested_details) and email is not None
    return ClaimRevision(
        **said.model_dump(),
        recommendation=(
            Recommendation.REQUEST_INFO
            if asks_the_merchant
            else Recommendation.REQUEST_REP_CLARIFICATION
        ),
        ambiguity=answered.ambiguity,
        requested_details=answered.requested_details,
        # Nothing goes to a merchant who is not being asked for anything. A report that asks a
        # representative to resolve something carries no merchant wording, here as everywhere
        # else (FR-2.7).
        email=email if asks_the_merchant else None,
        reinvestigate=answered.needs_fresh_investigation,
    )


async def rework_screening_report(
    *,
    case_record: CaseRecord,
    context: ClaimContext,
    findings: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange],
    structured: StructuredModel,
    events: EventStream,
) -> ClaimRevision:
    """Answer a representative who wrote back about a claim the quick checks turned away.

    **The verdict is not open and nothing here can reopen it.** The checks are arithmetic and
    their answer does not depend on anybody's judgement (FR-0.6), so feedback cannot make an
    ineligible claim eligible (FR-R.8). The agent is told to say that plainly, with the actual
    reason, rather than to apologise in general terms.

    **Only the merchant's wording may change**, and only when the report had wording to begin
    with. Everything else the model can fill in is dropped here rather than merely discouraged,
    so the guarantee is structural: no answer, however it is worded, can alter what the checks
    decided or what this claim recommends.

    Args:
        case_record: The case and the records the screen read.
        context: The facts the screen worked out.
        findings: The screen's own sentences saying why the claim was stopped.
        drafted_email: The wording currently going to the merchant, or `None` when the claim
            goes to a representative instead and nothing is being sent.
        feedback: What the representative said, in their own words.
        conversation: Every earlier round, oldest first.
        structured: The model, constrained to answer on a form (NFR-2).
        events: Where the rework narrates itself.

    Returns:
        A reply, and the merchant's email reworded where that was what they asked for.
    """
    await events.emit(
        EventKind.LINE_STARTED,
        "Answering the representative about this claim.",
    )

    try:
        answered = await structured.ask(
            RevisedClaimReport,
            build_screening_revision_messages(
                case=case_record.case,
                context=context,
                findings=findings,
                drafted_email=drafted_email,
                feedback=feedback,
                conversation=conversation,
            ),
        )
    except ClaimAgentError as failure:
        return _a_reply_that_could_not_be_written(failure, case_id=case_record.case.case_id)

    reworded = (
        _the_merchant_email(
            answered, contact_email=case_record.case.contact_email, existing=drafted_email
        )
        if drafted_email is not None
        else None
    )
    return ClaimRevision(
        reply=answered.reply_to_representative,
        changed=answered.changed,
        left_unchanged=answered.left_unchanged,
        needs_reply=answered.needs_more_from_representative,
        # Everything else the form can carry is dropped here rather than merely discouraged. A
        # stopped claim recommends nothing, asks the merchant for nothing, and is never
        # investigated again — and none of that is a matter of what the model wrote
        # (FR-0.6, FR-R.8).
        email=reworded if reworded != drafted_email else None,
    )


def _anything_to_change(answered: RevisedClaimReport) -> bool:
    """Whether the answer actually asks for anything about the report to be different.

    A reply on its own is an ordinary answer: a representative asks a question, the agent
    answers it, and the report is right as it stands. Telling that apart from a rework matters
    because the alternative is applying a form full of blanks — which would read as "nothing
    is unclear any more, nothing is needed from the merchant, send them nothing", none of
    which the agent said.
    """
    return (
        answered.ambiguity is not None
        or bool(answered.requested_details)
        or answered.email_subject is not None
        or answered.email_body is not None
    )


def _the_merchant_email(
    answered: RevisedClaimReport, *, contact_email: str | None, existing: DraftedEmail | None
) -> DraftedEmail | None:
    """The merchant's email as it should now read, or nothing to change it.

    `None` covers three different things and they all end the same way: the model left the
    wording alone, it wrote only half an email, or it decided nothing should be sent. The
    caller keeps whatever the report already had, which is right for the first two and for
    the third is caught by the recommendation instead.

    The address is never the model's to write. It comes from the claim, as it does everywhere
    else in this system (FR-3.2).

    Raises nothing. Wording that carries a figure is refused by the checks that build a
    merchant email elsewhere; there is no amount on a report that names no product, so there
    is nothing here for a figure to be checked against.
    """
    if answered.email_subject is None or answered.email_body is None:
        return existing
    return DraftedEmail(to=contact_email, subject=answered.email_subject, body=answered.email_body)


def _a_reply_that_could_not_be_written(failure: ClaimAgentError, *, case_id: str) -> ClaimRevision:
    """Report a model that could not be reached, as something a representative can act on.

    Nothing about the report changes and the representative is told why, so they can send it
    back again or decide on it as it stands. An error page would lose the message as well as
    the answer (NFR-4).
    """
    logger.warning(
        "claim_reply_could_not_be_written", case_id=case_id, failure=type(failure).__name__
    )
    return ClaimRevision(reply=f"{failure.message} {_COULD_NOT_REWORK}")
