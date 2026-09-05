"""What happens when a representative writes back about a report.

A representative reads a report and types something: what is wrong with it, a question, an
answer to a question it asked them, or a request to look at the claim again. **Whatever they
type, the agent receives it and answers.** There is no message this system refuses to pass on,
and no report kind that swallows one — the reply may be that a rule cannot be bent, but it is
a reply, written for them, about their claim.

What the agent may then *change* depends on what the report is, and that is decided here
rather than by what the agent wrote:

- **A report about one damaged product** is reworked in full: findings, judgements, the
  figure and the merchant's email (FR-R.9).
- **A report about a claim nobody could split into products** may have what is still unclear,
  what the merchant is asked for, and its email reworked. It can never be given an amount,
  because nothing on it was ever priced — so where the representative settles the split, the
  claim is investigated again instead, which is the only honest route from "we cannot tell
  which product" to "here is what to pay" (FR-1a.4).
- **A report for a claim the quick checks turned away** may have only its merchant email
  reworded. Its verdict is arithmetic and no message can overturn one (FR-0.6, FR-R.8).

**Nothing here sends anything or moves any money**, whichever path a message takes. The agent
holds the investigation's read-only tools and no others (FR-R.6, FR-3.1).

**Nothing here raises for anything that can happen to a claim.** A model that cannot be
reached, ShipBob failing, a run that used up its steps: each comes back as a reply saying so,
with the report unchanged, because a representative must be left with something to act on
rather than an error page (NFR-4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.precedent_context import precedent_for_line
from claim_agent.agent.prompts import EarlierExchange
from claim_agent.agent.revise import (
    ClaimRevision,
    LineRevision,
    ReportUnderReview,
    rework_claim_report,
    rework_line,
    rework_screening_report,
)
from claim_agent.agent.run import investigate_claim
from claim_agent.api.deps import ModelsFor
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, build_claim_lines
from claim_agent.domain.evidence import SHARED_EVIDENCE
from claim_agent.domain.models import Attachment, UtcDatetime, Verdict
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import nothing_priced_yet
from claim_agent.errors import ClaimAgentError, StorageError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.gather import gather_case_record
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.preflight.service import run_preflight
from claim_agent.report.build import (
    build_investigation_reports,
    build_revised_report,
    report_for_one_product,
)
from claim_agent.report.models import (
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ReportState,
    ScreeningReportContent,
)
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)

_COULD_NOT_READ_THE_CLAIM = (
    "This claim's records could not be read from ShipBob, so I could not answer properly and "
    "nothing in the report has changed. Send it back again to try once more."
)
"""What a representative is told when the claim cannot be re-read.

Written as the agent would say it, because from where they sit it *is* the agent answering.
It names what they can do next, because being told only that something failed leaves somebody
stuck (NFR-4).
"""

_NO_MODEL = (
    "The model that would answer you could not be reached, so nothing in this report has "
    "changed. Send it back again to try once more."
)
"""What a representative is told when no model can be built to answer them."""


@dataclass(frozen=True)
class Written:
    """Everything a representative's message produced, ready to be written down.

    Kept together because the two halves are written in one go and read in one go: the report
    they will see next, and any other reports the message caused to exist — which happens when
    a claim is investigated again because they settled what it is for.

    `alongside` is empty for every message that did not cause a fresh investigation, which is
    almost all of them.
    """

    report: Report
    alongside: tuple[Report, ...] = ()


async def answer_the_representative(
    parked: Report,
    *,
    feedback: str,
    at: UtcDatetime,
    reports: ReportStore,
    shipbob: ShipBobClient,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    models: ModelsFor,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> Written:
    """Give a representative's message to the agent, and write down what came back.

    Args:
        parked: The report as it stands, with their message already recorded on it.
        feedback: What they said, in their own words, kept exactly as written.
        at: When this is happening. Handed in rather than read from a clock, so the same
            message writes the same version twice (NFR-1).
        reports: Where reports are kept, and where the new version goes.
        shipbob: Reads the case, its parcel and its order again.
        evidence: Reads the claim's images and prices the shipment.
        fetcher: Downloads an image so a model can look at it.
        models: A way to build the models, asked for only once there is something to answer.
        memory: What a representative has corrected for this merchant, read again when a claim
            is investigated afresh.
        precedent_store: The closed claims this service has handled (FR-S.5).
        policy: The thresholds this claim is judged by (FR-0.7).

    Returns:
        The next version of the report, and any product reports a fresh investigation
        produced beside it. Never raises for anything that can happen to a claim.
    """
    try:
        record = await gather_case_record(parked.case_id, shipbob)
    except ClaimAgentError as failure:
        logger.warning(
            "reply_could_not_read_the_case",
            case_id=parked.case_id,
            failure=type(failure).__name__,
        )
        return _only_a_reply(parked, _COULD_NOT_READ_THE_CLAIM, feedback=feedback, at=at)

    try:
        chat, structured = models()
    except ClaimAgentError as failure:
        logger.warning(
            "reply_needs_a_model_it_cannot_have",
            case_id=parked.case_id,
            failure=type(failure).__name__,
        )
        return _only_a_reply(parked, _NO_MODEL, feedback=feedback, at=at)

    answered = await _ask_the_agent(
        parked,
        feedback=feedback,
        record=record,
        reports=reports,
        evidence=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        precedent_store=precedent_store,
        policy=policy,
    )

    if isinstance(answered, ClaimRevision) and answered.settled:
        return await _look_into_what_they_settled(
            parked,
            answered,
            feedback=feedback,
            at=at,
            record=record,
            reports=reports,
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            precedent_store=precedent_store,
            policy=policy,
        )

    if isinstance(answered, ClaimRevision) and answered.reinvestigate:
        return await _investigate_the_claim_again(
            parked,
            answered,
            feedback=feedback,
            at=at,
            reports=reports,
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            shipbob=shipbob,
            memory=memory,
            precedent_store=precedent_store,
            policy=policy,
        )

    return Written(build_revised_report(parked, answered, feedback=feedback, at=at))


async def _ask_the_agent(
    parked: Report,
    *,
    feedback: str,
    record: CaseRecord,
    reports: ReportStore,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> LineRevision | ClaimRevision:
    """Put the message to the agent, in the shape this kind of report calls for.

    The three shapes are genuinely different questions, which is why they are three prompts
    rather than one with branches in it: what a product report may become, what an unsettled
    claim may become, and what a stopped claim may become have almost nothing in common.

    `chat` is only used by the product rework, which runs the tool-use loop. The other two ask
    one question and hold no tools, because there is nothing they could look at that would
    change their answer.
    """
    content = parked.content

    if isinstance(content, InvestigationReportContent):
        return await rework_line(
            under_review=ReportUnderReview(
                line=content.line,
                context=content.context,
                attachments=content.attachments,
                recommendation=content.outcome.recommendation,
                amount=content.amount,
                evidence=content.evidence,
                assessments=content.assessments,
                concerns=content.concerns,
                drafted_email=parked.drafted_email,
                conversation=what_has_been_said(parked),
                siblings=the_other_products(parked, reports),
            ),
            feedback=feedback,
            record=record,
            evidence_client=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            events=EventStream(),
            policy=policy,
            precedent=precedent_for_line(
                store=precedent_store,
                case=record.case,
                line=content.line,
                policy=policy,
                # The three that describe the parcel, exactly as a first pass supplies them.
                # The report has settled all four by now, and handing over the fourth would
                # make a rework search on a different pattern from the investigation that
                # preceded it — so the same claim could be shown different past claims for no
                # stated reason.
                shared_evidence=tuple(
                    finding for finding in content.evidence if finding.kind in SHARED_EVIDENCE
                ),
            ),
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
            events=EventStream(),
        )

    return await rework_screening_report(
        case_record=record,
        context=content.context,
        findings=content.findings,
        drafted_email=parked.drafted_email,
        feedback=feedback,
        conversation=what_has_been_said(parked),
        structured=structured,
        events=EventStream(),
    )


async def _look_into_what_they_settled(
    parked: Report,
    answered: ClaimRevision,
    *,
    feedback: str,
    at: UtcDatetime,
    record: CaseRecord,
    reports: ReportStore,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> Written:
    """Look into the products a representative just named, and nothing else (FR-1a.4).

    **This is what a representative naming a product should cost: one pass per product.** The
    heavy alternative — investigating the whole claim again — re-reads every image, re-splits
    the claim and re-judges everything, and on a claim nobody could split it very often comes
    back unable to split it a second time. A representative who has just answered that exact
    question should not be made to wait for the system to fail at it again.

    So their answer is turned straight into claim lines, matched against the order the way the
    split would have matched them, and each one is investigated on its own. Their instruction
    travels with it: if they said to pay the claim, the run comes back approved, with the
    figure, because the rules that would withhold it encode the agent's uncertainty and they
    have just corrected it.

    The claim-level report is superseded rather than overwritten — its conversation is the
    record of how this was reached (FR-R.13) — and each product's report is written beside it.
    """
    lines = build_claim_lines(
        parked.case_id,
        tuple(
            ClaimedProduct(name=product.name, quantity=product.quantity, sku=product.sku)
            for product in answered.settled
        ),
        record.order,
    )
    # Each product on its own, at the same time, exactly as an investigation does it: they need
    # nothing from each other, and one slow product must not hold up a simple one (FR-1b.3).
    #
    # Each run fetches the priced invoice and reads the photographs for itself, because each
    # builds its own memo of what it has looked at. On a claim of one product — which is what a
    # representative naming one almost always means — that costs nothing; on several it pays
    # for the same invoice more than once.
    looked_into = await asyncio.gather(
        *(
            rework_line(
                under_review=_nothing_established_yet(line, parked, ambiguity=answered.ambiguity),
                feedback=feedback,
                record=record,
                evidence_client=evidence,
                fetcher=fetcher,
                chat=chat,
                structured=structured,
                events=EventStream(),
                policy=policy,
                precedent=precedent_for_line(
                    store=precedent_store, case=record.case, line=line, policy=policy
                ),
            )
            for line in lines
        )
    )

    produced = _placed_beside_what_is_already_there(
        tuple(
            report_for_one_product(
                line=done.investigation,
                case=record.case,
                carrier=record.shipment.carrier if record.shipment is not None else None,
                context=_context_of(parked),
                attachments=_attachments_of(parked),
                at=at,
            )
            for done in looked_into
            if done.investigation is not None
        ),
        reports=reports,
    )

    logger.info(
        "settled_products_looked_into",
        case_id=parked.case_id,
        named=len(lines),
        produced=len(produced),
    )
    return Written(
        build_revised_report(
            parked,
            answered.model_copy(
                update={"reply": _also(answered.reply, _what_it_produced(produced))}
            ),
            feedback=feedback,
            at=at,
            reinvestigated=True,
        ),
        alongside=produced,
    )


def _nothing_established_yet(
    line: ClaimLine, parked: Report, *, ambiguity: str | None
) -> ReportUnderReview:
    """One product to look into, with an honest account of what is known about it: nothing.

    A claim nobody could split was never investigated, so there are no findings to carry
    forward and no figure to start from. Saying that plainly is better than seeding the run
    with a blank report that looks like one somebody produced — the run reads what it is given
    as a record of what was seen, and there is nothing to have seen.
    """
    return ReportUnderReview(
        line=line,
        context=_context_of(parked),
        attachments=_attachments_of(parked),
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
        amount=nothing_priced_yet(),
        concerns=(ambiguity,) if ambiguity else (),
        conversation=what_has_been_said(parked),
        siblings=(),
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
    reports: ReportStore,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    shipbob: ShipBobClient,
    memory: MerchantMemory,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> Written:
    """Investigate the claim again, because the representative settled what it is for.

    This is the one route from a claim nobody could divide into products to a report somebody
    can approve. It is a real investigation, not a rewording: the evidence is read again, the
    claim is split again, and each product is judged on what is actually in the photographs —
    which is the only way a figure can exist at all (FR-1.21).

    **What the representative said reaches it as a correction against the merchant**, written
    the moment they sent the report back (FR-R.14), and read back here as starting context
    (FR-0.5). So the split is settled by their words without any new path being invented for
    them: the same channel that improves the merchant's *next* claim improves this one.

    A claim that fails the quick checks on the way through is possible in principle — the
    thresholds can change between one screening and the next (FR-0.7) — and produces no
    products, so the report is carried through with the agent's reply and nothing else.

    Returns:
        The claim-level report's next version, and the product reports the investigation
        produced. Both are the caller's to write down.
    """
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
        return Written(
            build_revised_report(parked, answered, feedback=feedback, at=at, reinvestigated=True)
        )

    investigated = await investigate_claim(
        record=screening.record,
        context=screening.context,
        evidence=evidence,
        fetcher=fetcher,
        chat=chat,
        structured=structured,
        events=EventStream(),
        policy=policy,
        precedent_store=precedent_store,
    )
    built = build_investigation_reports(screening, investigated, at=at)

    # A claim still nobody can split produces another claim-level report under the very same
    # name. Writing that as version 1 would overwrite the version the representative was
    # looking at and lose the conversation with it (FR-R.13), so its findings are folded into
    # the next version instead and only genuinely new reports are written beside it.
    superseded = tuple(report for report in built if report.report_id == parked.report_id)
    fresh = _placed_beside_what_is_already_there(
        tuple(report for report in built if report.report_id != parked.report_id),
        reports=reports,
    )

    revised = build_revised_report(
        parked,
        answered.model_copy(update={"reply": _also(answered.reply, _what_it_produced(fresh))}),
        feedback=feedback,
        at=at,
        reinvestigated=True,
    )
    if superseded:
        revised = revised.model_copy(
            update={
                "recommendation": superseded[0].recommendation,
                "amount_usd": superseded[0].amount_usd,
                "drafted_email": superseded[0].drafted_email,
                "content": superseded[0].content,
            }
        )

    logger.info(
        "claim_investigated_again",
        case_id=parked.case_id,
        produced=len(fresh),
        still_unsettled=bool(superseded),
    )
    return Written(revised, alongside=fresh)


def _placed_beside_what_is_already_there(
    built: Sequence[Report], *, reports: ReportStore
) -> tuple[Report, ...]:
    """Fit freshly investigated reports around the ones a claim already has.

    **This is the guard against a fresh investigation destroying a decision.** Every report a
    build produces is version 1, and writing one replaces whatever shares its name — so a claim
    whose products were already reported on would have those reports written straight over,
    taking their review state, their conversation and the record of what a representative
    decided with them.

    Three cases, and they are genuinely different:

    - **Nothing there yet.** The report is written as it is, version 1.
    - **Something there, still under review.** The new findings become its next version, and
      what a representative has already done to it travels with them (FR-R.13, FR-C.1).
    - **Something there and approved.** It is left completely alone. Approving is final and
      terminal (FR-2.9), and investigating a claim again is not a way round that — a line whose
      email is about to go out must not change underneath the person who released it.

    A store that cannot be read withholds the report rather than writing it. Losing findings
    that can be produced again is the lesser harm; overwriting an approval cannot be undone.
    """
    placed: list[Report] = []
    for report in built:
        try:
            existing = reports.get(report.report_id)
        except StorageError:
            logger.warning("fresh_findings_withheld", report_id=report.report_id)
            continue

        if existing is None:
            placed.append(report)
        elif existing.state is ReportState.APPROVED:
            logger.info("fresh_findings_withheld_from_an_approved_line", report_id=report.report_id)
        else:
            placed.append(
                report.model_copy(
                    update={
                        "version": existing.version + 1,
                        "decisions_taken": existing.decisions_taken,
                        "reviews": existing.reviews,
                        "revisions": existing.revisions,
                    }
                )
            )
    return tuple(placed)


def _what_it_produced(fresh: Sequence[Report]) -> str:
    """One sentence saying what investigating the claim again actually turned up.

    **The agent's reply is written before the investigation runs**, so on its own it can only
    say what is about to happen. Left at that, a representative reads "I am investigating this
    again", waits, and then has to work out from the report whether anything came of it —
    which is exactly what made the first version of this read as broken.

    So the outcome is added afterwards, by code, because code is the only thing that knows it.
    """
    if not fresh:
        return (
            "I had the whole claim investigated again, and it still could not establish which "
            "products this claim is for — so there is no product to price and nothing new to "
            "approve. What it now says is unclear is in the report above."
        )
    named = ", ".join(sorted(report.product_name or report.report_id for report in fresh))
    return (
        f"I had the whole claim investigated again. It produced a report for {named}, below, "
        "each with its own recommendation for you to decide on."
    )


def _also(reply: str, added: str) -> str:
    """Put a sentence code knows after one the agent wrote, without running them together."""
    return f"{reply.rstrip()} {added}" if reply.strip() else added


def _only_a_reply(parked: Report, said: str, *, feedback: str, at: UtcDatetime) -> Written:
    """The next version of a report that nothing could change, carrying what was said.

    Used where the agent was never reached at all. The report keeps every finding it had and
    the representative is told why, so they can send it back again or decide on it as it
    stands (NFR-4).
    """
    return Written(
        build_revised_report(parked, ClaimRevision(reply=said), feedback=feedback, at=at)
    )


def what_has_been_said(report: Report) -> tuple[EarlierExchange, ...]:
    """Every earlier round of this report going back and forth, oldest first (FR-R.12).

    Empty the first time, which is the usual case. From the second onwards it is what stops the
    agent undoing an earlier correction while answering a later one — the only thing that
    distinguishes one pass from the next, since it is the same agent every time.
    """
    return tuple(
        EarlierExchange(feedback=turn.feedback, reply=turn.reply, changed=turn.changed)
        for turn in report.revisions
    )


def the_other_products(report: Report, reports: ReportStore) -> tuple[ClaimLine, ...]:
    """The claim's other damaged products, read from their own reports (FR-1b.2).

    Looked up rather than stored on the report, for the same reason the rows beside a report
    are: what the other products are is a fact about the claim now, not when this report was
    written.

    A store that cannot be read gives none rather than failing the answer. Knowing what else
    was claimed for makes a rework better informed; not knowing costs a sentence of context,
    and losing the whole answer over it would cost the representative their reply (NFR-4).
    """
    try:
        claim = reports.for_case(report.case_id)
    except StorageError:
        logger.warning("reply_could_not_read_the_other_products", case_id=report.case_id)
        return ()

    return tuple(
        other.content.line
        for other in claim.reports
        if other.report_id != report.report_id
        and isinstance(other.content, InvestigationReportContent)
    )
