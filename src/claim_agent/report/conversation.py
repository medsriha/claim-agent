from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel

from claim_agent.agent.directed import DirectedPayment, approve_as_directed, what_pricing_produced
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import ClaimFindings, model_name
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.precedent_context import precedent_for_claim
from claim_agent.agent.prompts import EarlierExchange
from claim_agent.agent.revise import (
    AnswerRevision,
    ClaimFindingsRevision,
    ClaimRevision,
    DirectedApproval,
    EmailRevision,
    ReportUnderReview,
    plan_report_reply,
    rework_claim_findings,
    rework_claim_report,
    rework_screening_report,
)
from claim_agent.agent.run import investigate_claim, invoice_for_claim
from claim_agent.agent.threads import PassThreads
from claim_agent.api.deps import ModelsFor
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, build_claim_lines
from claim_agent.domain.evidence import SHARED_EVIDENCE
from claim_agent.domain.models import Attachment, UtcDatetime, Verdict
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import nothing_priced_yet
from claim_agent.errors import ClaimAgentError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.gather import gather_case_record
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.preflight.service import run_preflight
from claim_agent.report.build import (
    build_investigation_report,
    build_revised_report,
    report_for_the_claim,
)
from claim_agent.report.models import (
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ScreeningReportContent,
)
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore

logger = get_logger(__name__)

_COULD_NOT_READ_THE_CLAIM = (
    "This claim's records could not be read from ShipBob, so I could not answer properly and "
    "nothing in the report has changed. Send it back again to try once more."
)
"""What a representative is told when the claim cannot be re-read."""

_NO_MODEL = (
    "The model that would answer you could not be reached, so nothing in this report has "
    "changed. Send it back again to try once more."
)
"""What a representative is told when no model can be built to answer them."""


async def answer_the_representative(
    parked: Report,
    *,
    feedback: str,
    at: UtcDatetime,
    shipbob: ShipBobClient,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    models: ModelsFor,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: Policy,
    threads: PassThreads | None = None,
    events: EventStream | None = None,
) -> Report:
    """Give a representative's message to the agent, and write down what came back."""
    active_events = events if events is not None else EventStream()
    await active_events.emit(
        EventKind.REVISION_STARTED,
        "Reviewing the representative's message.",
    )

    try:
        chat, structured = models()
    except ClaimAgentError as failure:
        logger.warning(
            "reply_needs_a_model_it_cannot_have",
            case_id=parked.case_id,
            failure=type(failure).__name__,
        )
        return _only_a_reply(parked, _NO_MODEL, feedback=feedback, at=at)

    directed_approval: DirectedApproval | None = None
    if isinstance(parked.content, InvestigationReportContent):
        planned = await plan_report_reply(
            under_review=_report_under_review(parked),
            feedback=feedback,
            structured=structured,
            events=active_events,
        )
        if isinstance(planned, DirectedApproval):
            directed_approval = planned
        elif planned is not None:
            return build_revised_report(parked, planned, feedback=feedback, at=at)

    try:
        record = await gather_case_record(parked.case_id, shipbob)
    except ClaimAgentError as failure:
        logger.warning(
            "reply_could_not_read_the_case",
            case_id=parked.case_id,
            failure=type(failure).__name__,
        )
        return _only_a_reply(parked, _COULD_NOT_READ_THE_CLAIM, feedback=feedback, at=at)

    if directed_approval is not None:
        return await _pay_the_report_as_directed(
            parked,
            directed_approval,
            feedback=feedback,
            at=at,
            record=record,
            evidence=evidence,
            chat=chat,
            policy=policy,
            events=active_events,
        )

    answered = await _ask_the_agent(
        parked,
        feedback=feedback,
        record=record,
        evidence=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        precedent_store=precedent_store,
        policy=policy,
        threads=threads,
        events=active_events,
    )

    if isinstance(answered, ClaimRevision) and answered.settled and answered.directed is not None:
        return await _pay_what_they_settled(
            parked,
            answered,
            answered.directed,
            feedback=feedback,
            at=at,
            record=record,
            evidence=evidence,
            chat=chat,
            policy=policy,
            events=active_events,
        )

    if isinstance(answered, ClaimRevision) and answered.settled:
        return await _look_into_what_they_settled(
            parked,
            answered,
            feedback=feedback,
            at=at,
            record=record,
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            precedent_store=precedent_store,
            policy=policy,
            threads=threads,
            events=active_events,
        )

    if isinstance(answered, ClaimRevision) and answered.reinvestigate:
        return await _investigate_the_claim_again(
            parked,
            answered,
            feedback=feedback,
            at=at,
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            shipbob=shipbob,
            memory=memory,
            precedent_store=precedent_store,
            policy=policy,
            threads=threads,
            events=active_events,
        )

    return build_revised_report(parked, answered, feedback=feedback, at=at)


async def _ask_the_agent(
    parked: Report,
    *,
    feedback: str,
    record: CaseRecord,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    precedent_store: PrecedentStore,
    policy: Policy,
    threads: PassThreads | None,
    events: EventStream,
) -> ClaimFindingsRevision | ClaimRevision | EmailRevision | AnswerRevision:
    """Put the message to the agent, in the shape this kind of report calls for."""
    content = parked.content

    if isinstance(content, InvestigationReportContent):
        return await rework_claim_findings(
            under_review=_report_under_review(parked),
            feedback=feedback,
            record=record,
            evidence_client=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            events=events,
            policy=policy,
            precedent=precedent_for_claim(
                store=precedent_store,
                case=record.case,
                lines=content.lines,
                policy=policy,
                shared_evidence=tuple(
                    finding for finding in content.evidence if finding.kind in SHARED_EVIDENCE
                ),
            ),
            threads=threads,
            thread_id=content.thread_id,
        )

    if isinstance(content, ClarificationReportContent):
        return await rework_claim_report(
            case_record=record,
            context=content.context,
            attachments=content.attachments,
            ambiguity=content.ambiguity,
            candidate_lines=content.candidate_lines,
            requested_details=content.requested_details,
            concerns=content.concerns,
            drafted_email=parked.drafted_email,
            feedback=feedback,
            conversation=what_has_been_said(parked),
            structured=structured,
            events=events,
        )

    return await rework_screening_report(
        case_record=record,
        context=content.context,
        findings=content.findings,
        drafted_email=parked.drafted_email,
        feedback=feedback,
        conversation=what_has_been_said(parked),
        structured=structured,
        events=events,
    )


def _report_under_review(report: Report) -> ReportUnderReview:
    """Read an investigated report into the shape used by both planning and full rework."""
    content = report.content
    if not isinstance(content, InvestigationReportContent):
        raise TypeError("Only an investigated report has findings to rework.")
    return ReportUnderReview(
        lines=content.lines,
        context=content.context,
        attachments=content.attachments,
        recommendation=content.outcome.recommendation,
        amount=content.amount,
        evidence=content.evidence,
        assessments=content.assessments,
        concerns=content.concerns,
        requested_details=content.requested_details,
        drafted_email=report.drafted_email,
        conversation=what_has_been_said(report),
    )


async def _look_into_what_they_settled(
    parked: Report,
    answered: ClaimRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    record: CaseRecord,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    precedent_store: PrecedentStore,
    policy: Policy,
    threads: PassThreads | None,
    events: EventStream,
) -> Report:
    """Look into the products a representative just named, and nothing else (FR-1a.4)."""
    lines = build_claim_lines(
        parked.case_id,
        tuple(
            ClaimedProduct(name=product.name, quantity=product.quantity, sku=product.sku)
            for product in answered.settled
        ),
        record.order,
    )

    looked_into = await rework_claim_findings(
        under_review=_nothing_established_yet(lines, parked, ambiguity=answered.ambiguity),
        feedback=feedback,
        record=record,
        evidence_client=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        events=events,
        policy=policy,
        precedent=precedent_for_claim(
            store=precedent_store, case=record.case, lines=lines, policy=policy
        ),
        threads=threads,
    )

    logger.info(
        "settled_products_looked_into",
        case_id=parked.case_id,
        named=len(lines),
        reworked=looked_into.reworked,
    )

    if looked_into.findings is None:
        return build_revised_report(
            parked,
            answered.model_copy(update={"reply": _also(answered.reply, looked_into.reply)}),
            feedback=feedback,
            at=at,
            reinvestigated=True,
        )

    built = report_for_the_claim(
        findings=looked_into.findings,
        case=record.case,
        carrier=record.shipment.carrier if record.shipment is not None else None,
        context=_context_of(parked),
        attachments=_attachments_of(parked),
        at=at,
    )
    return _findings_became_the_next_version(
        parked,
        built,
        answered.model_copy(update={"reply": _also(answered.reply, _what_it_produced(built))}),
        feedback=feedback,
        at=at,
    )


async def _pay_the_report_as_directed(
    parked: Report,
    planned: DirectedApproval,
    *,
    feedback: str,
    at: UtcDatetime,
    record: CaseRecord,
    evidence: EvidenceClient,
    chat: BaseChatModel,
    policy: Policy,
    events: EventStream,
) -> Report:
    """Approve an investigated report because the representative said to (FR-2.8)."""
    content = parked.content
    if not isinstance(content, InvestigationReportContent):
        raise TypeError("Only an investigated report can be approved as it stands.")

    paid = await approve_as_directed(
        lines=content.lines,
        directed=planned.directed,
        invoice=await invoice_for_claim(record=record, evidence=evidence, cache=ObservationCache()),
        policy=policy,
        contact_email=record.case.contact_email,
        model=model_name(chat),
        events=events,
        evidence=content.evidence,
        assessments=content.assessments,
        concerns=content.concerns,
        earlier_amount=content.amount,
    )
    logger.info(
        "report_paid_as_directed",
        case_id=parked.case_id,
        products=len(content.lines),
        recommendation=paid.outcome.recommendation.value,
    )
    return build_revised_report(
        parked,
        ClaimFindingsRevision(
            findings=paid.model_copy(update={"thread_id": content.thread_id}),
            reply=_also(planned.reply, what_pricing_produced(paid)),
            changed=planned.changed or _what_a_directed_payment_changed(paid),
            left_unchanged=planned.left_unchanged,
            needs_reply=planned.needs_reply or not paid.outcome.recommendation.is_approval,
        ),
        feedback=feedback,
        at=at,
    )


async def _pay_what_they_settled(
    parked: Report,
    answered: ClaimRevision,
    directed: DirectedPayment,
    *,
    feedback: str,
    at: UtcDatetime,
    record: CaseRecord,
    evidence: EvidenceClient,
    chat: BaseChatModel,
    policy: Policy,
    events: EventStream,
) -> Report:
    """Pay the products a representative just named, because they said to (FR-1a.4, FR-2.8)."""
    lines = build_claim_lines(
        parked.case_id,
        tuple(
            ClaimedProduct(name=product.name, quantity=product.quantity, sku=product.sku)
            for product in answered.settled
        ),
        record.order,
    )

    paid = await approve_as_directed(
        lines=lines,
        directed=directed,
        invoice=await invoice_for_claim(record=record, evidence=evidence, cache=ObservationCache()),
        policy=policy,
        contact_email=record.case.contact_email,
        model=model_name(chat),
        events=events,
        concerns=(answered.ambiguity,) if answered.ambiguity else (),
    )
    logger.info(
        "settled_products_paid_as_directed",
        case_id=parked.case_id,
        named=len(lines),
        recommendation=paid.outcome.recommendation.value,
    )

    built = report_for_the_claim(
        findings=paid,
        case=record.case,
        carrier=record.shipment.carrier if record.shipment is not None else None,
        context=_context_of(parked),
        attachments=_attachments_of(parked),
        at=at,
    )
    return _findings_became_the_next_version(
        parked,
        built,
        answered.model_copy(
            update={
                "reply": _also(answered.reply, what_pricing_produced(paid)),
                "changed": answered.changed or _what_a_directed_payment_changed(paid),
                "needs_reply": answered.needs_reply or not paid.outcome.recommendation.is_approval,
            }
        ),
        feedback=feedback,
        at=at,
        reinvestigated=False,
    )


def _what_a_directed_payment_changed(paid: ClaimFindings) -> tuple[str, ...]:
    """Say what a directed payment did to the report, one item each (FR-R.10)."""
    if not paid.outcome.recommendation.is_approval:
        return ()
    named = ", ".join(line.product_name for line in paid.lines)
    return (
        f"Approved {named} at ${paid.amount.amount_usd} as you directed, priced from the "
        "invoice rather than investigated again.",
        "Finished the approval email with that figure.",
    )


def _nothing_established_yet(
    lines: Sequence[ClaimLine], parked: Report, *, ambiguity: str | None
) -> ReportUnderReview:
    """The claim to look into, with an honest account of what is known about it: nothing."""
    return ReportUnderReview(
        lines=tuple(lines),
        context=_context_of(parked),
        attachments=_attachments_of(parked),
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
        amount=nothing_priced_yet(),
        concerns=(ambiguity,) if ambiguity else (),
        conversation=what_has_been_said(parked),
    )


def _context_of(report: Report) -> ClaimContext:
    """The facts the deterministic screen worked out, whichever kind of report holds them."""
    return report.content.context


def _attachments_of(report: Report) -> tuple[Attachment, ...]:
    """Every image on the claim, or none for a report that never listed any."""
    content = report.content
    if isinstance(content, ScreeningReportContent):
        return ()
    return content.attachments


async def _investigate_the_claim_again(
    parked: Report,
    answered: ClaimRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    shipbob: ShipBobClient,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: Policy,
    threads: PassThreads | None,
    events: EventStream,
) -> Report:
    """Investigate the claim again, because the representative asked for it."""
    try:
        screening = await run_preflight(
            case_id=parked.case_id,
            client=shipbob,
            memory=memory,
            policy=policy,
            evaluated_at=at,
        )
    except ClaimAgentError as failure:
        logger.warning(
            "fresh_investigation_could_not_start",
            case_id=parked.case_id,
            failure=type(failure).__name__,
        )
        return _only_a_reply(parked, _COULD_NOT_READ_THE_CLAIM, feedback=feedback, at=at)

    if screening.verdict is Verdict.TERMINAL:
        logger.info("fresh_investigation_stopped_by_the_checks", case_id=parked.case_id)
        return build_revised_report(parked, answered, feedback=feedback, at=at, reinvestigated=True)

    investigated = await investigate_claim(
        record=screening.record,
        context=screening.context,
        evidence=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        events=events,
        policy=policy,
        precedent_store=precedent_store,
        threads=threads,
    )
    built = build_investigation_report(screening, investigated, at=at)

    logger.info(
        "claim_investigated_again",
        case_id=parked.case_id,
        products=len(built.product_names),
    )
    return _findings_became_the_next_version(
        parked,
        built,
        answered.model_copy(update={"reply": _also(answered.reply, _what_it_produced(built))}),
        feedback=feedback,
        at=at,
    )


def _findings_became_the_next_version(
    parked: Report,
    built: Report,
    revision: ClaimRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    reinvestigated: bool = True,
) -> Report:
    """Make freshly investigated findings the next version of the report they replace."""
    revised = build_revised_report(
        parked, revision, feedback=feedback, at=at, reinvestigated=reinvestigated
    )
    if isinstance(parked.content, ScreeningReportContent):
        logger.error("fresh_findings_withheld_from_a_stopped_claim", report_id=parked.report_id)
        return revised
    return revised.model_copy(
        update={
            "product_names": built.product_names,
            "recommendation": built.recommendation,
            "amount_usd": built.amount_usd,
            "confidence": built.confidence,
            "drafted_email": built.drafted_email,
            "content": built.content,
        }
    )


def _what_it_produced(built: Report) -> str:
    """One sentence saying what investigating the claim actually turned up."""
    if not built.product_names:
        return (
            "I had the claim investigated again, and it still could not establish which "
            "products this claim is for — so there is nothing to price and nothing new to "
            "approve. What it now says is unclear is in the report above."
        )
    named = ", ".join(built.product_names)
    return (
        f"I had the claim investigated, and the report above now covers {named}, with one "
        "recommendation for you to decide on."
    )


def _also(reply: str, added: str) -> str:
    """Put a sentence code knows after one the agent wrote, without running them together."""
    return f"{reply.rstrip()} {added}" if reply.strip() else added


def _only_a_reply(parked: Report, said: str, *, feedback: str, at: UtcDatetime) -> Report:
    """The next version of a report that nothing could change, carrying what was said."""
    return build_revised_report(parked, AnswerRevision(reply=said), feedback=feedback, at=at)


def what_has_been_said(report: Report) -> tuple[EarlierExchange, ...]:
    """Every earlier round of this report going back and forth, oldest first (FR-R.12)."""
    return tuple(
        EarlierExchange(feedback=turn.feedback, reply=turn.reply, changed=turn.changed)
        for turn in report.revisions
    )
