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
from claim_agent.agent.prompts import EarlierExchange, build_revision_messages
from claim_agent.agent.run import invoice_for_claim
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    EvidenceJudgement,
    RevisionConclusion,
)
from claim_agent.agent.tools import investigation_tools
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Attachment, DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import AmountDerivation
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


class LineRevision(BaseModel):
    """What one rework produced, whether or not it managed to rework anything.

    The same shape either way, deliberately, so a caller reads it rather than catching
    something. A rework that did not happen is an ordinary outcome to report to a
    representative, not an error page (NFR-4).

    Frozen, because it is the account of something that has already happened.

    Fields:
        investigation: The reworked findings, settled by the same rules the first pass ran
            through, or `None` when the run never reached an answer. `None` means the report
            keeps everything it already said.
        reply: What the agent says back to the representative, in plain words. Where the
            rework did not happen, this is the reason it did not. Where a note asked for
            something the rules forbid, this is where it says so (FR-R.8).
        changed: What was changed in response to the note, one item each (FR-R.10).
        left_unchanged: What the note did not bear on and was carried forward as it was.
        needs_reply: Whether the agent's reply contains a question it needs the
            representative to answer before this can be settled. It changes nothing about
            what is recommended; it says the conversation is waiting on a person.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation: LineInvestigation | None
    reply: str
    changed: tuple[str, ...] = ()
    left_unchanged: tuple[str, ...] = ()
    needs_reply: bool = False

    @property
    def reworked(self) -> bool:
        """Whether the report was actually reworked.

        Worked out from whether there are findings rather than stored beside them, so the
        two can never contradict each other — the same reasoning that keeps a run's "gave
        up" off its record as a separate flag.
        """
        return self.investigation is not None


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
