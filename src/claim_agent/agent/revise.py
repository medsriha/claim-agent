"""Layer R — reworking one product's report after a representative sent it back."""

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
    SettledProduct,
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

# What the run is asked once it has stopped looking at things.
CLOSING_REQUEST = (
    "Now give the reworked report for this one product: all four pieces of evidence, the "
    "four questions where the evidence is there, what should be paid for, your next action, "
    "the merchant email where that action addresses them, what you changed, what you left "
    "alone, and your reply to the representative."
)
# What a representative is told when the run did not reach an answer.
_COULD_NOT_REWORK = (
    "This report could not be reworked, so nothing in it has changed. Send it back again to "
    "try once more, or decide on it as it stands."
)


class ReportUnderReview(BaseModel):
    """The report a representative sent back, in the parts a rework needs (FR-R.2)."""

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
    """What the agent says back to a representative, whatever kind of report it was."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reply: str
    changed: tuple[str, ...] = ()
    left_unchanged: tuple[str, ...] = ()
    needs_reply: bool = False

    @property
    def reworked(self) -> bool:
        """Whether anything about the report actually changed."""
        return False


class LineRevision(Reply):
    """A reworked report for one damaged product (FR-R.9)."""

    investigation: LineInvestigation | None = None

    @property
    def reworked(self) -> bool:
        """Whether the report was actually reworked."""
        return self.investigation is not None


class ClaimRevision(Reply):
    """A reworked report about a whole claim rather than one product (FR-1a.4, FR-0.4)."""

    recommendation: Recommendation | None = None
    ambiguity: str | None = None
    requested_details: tuple[str, ...] = ()
    email: DraftedEmail | None = None
    settled: tuple[SettledProduct, ...] = ()
    reinvestigate: bool = False

    @property
    def reworked(self) -> bool:
        """Whether anything about the report actually changed."""
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
    """Rework one product's report around what a representative said (FR-R.1 to FR-R.11)."""
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
        # Nothing is pinned from the claim's shared evidence, which is the point of a
        # rework: FR-R.5's own example of feedback is a correction to a shared finding, and
        # pinning them would make that the one correction impossible to make.
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
    """Report a run that stopped before it could answer (FR-1.16, NFR-4)."""
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
    """Fill in whatever the reworked answer left out, from the report it is reworking."""
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
    """Put a settled finding back into the form the model answers on."""
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
    """Say when a correction bears on the claim's other products too (FR-R.1a, FR-1a.3)."""
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
    """Answer a representative who wrote back about a claim whose split was never settled."""
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
        # The agent answered without changing the report — a question, or a request to
        # investigate instead. Filling in what the model left blank would drop a merchant
        # email nobody asked to drop.
        return ClaimRevision(
            **said.model_dump(),
            settled=answered.settled_products,
            reinvestigate=answered.needs_fresh_investigation,
        )

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
        settled=answered.settled_products,
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
    """Answer a representative who wrote back about a claim the quick checks turned away."""
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
        # Dropped rather than merely discouraged: a stopped claim recommends nothing, asks
        # the merchant for nothing, and is never investigated again, whatever the model
        # wrote (FR-0.6, FR-R.8).
        email=reworded if reworded != drafted_email else None,
    )


def _anything_to_change(answered: RevisedClaimReport) -> bool:
    """Whether the answer actually asks for anything about the report to be different."""
    return (
        answered.ambiguity is not None
        or bool(answered.requested_details)
        or answered.email_subject is not None
        or answered.email_body is not None
    )


def _the_merchant_email(
    answered: RevisedClaimReport, *, contact_email: str | None, existing: DraftedEmail | None
) -> DraftedEmail | None:
    """The merchant's email as it should now read, or nothing to change it."""
    if answered.email_subject is None or answered.email_body is None:
        return existing
    return DraftedEmail(to=contact_email, subject=answered.email_subject, body=answered.email_body)


def _a_reply_that_could_not_be_written(failure: ClaimAgentError, *, case_id: str) -> ClaimRevision:
    """Report a model that could not be reached, as something a representative can act on."""
    logger.warning(
        "claim_reply_could_not_be_written", case_id=case_id, failure=type(failure).__name__
    )
    return ClaimRevision(reply=f"{failure.message} {_COULD_NOT_REWORK}")
