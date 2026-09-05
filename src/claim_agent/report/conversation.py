"""What happens when a representative writes back about a report.

A representative reads a report and types something: what is wrong with it, a question, an
answer to a question it asked them, or a request to look at the claim again. **Whatever they
type, the agent receives it and answers.** There is no message this system refuses to pass on,
and no report kind that swallows one — the reply may be that a rule cannot be bent, but it is
a reply, written for them, about their claim.

What the agent may then *change* depends on what the report is, and that is decided here
rather than by what the agent wrote:

- **A report about an investigated claim** is reworked in full: findings, judgements, the
  figure and the merchant's email, across every product on it (FR-R.9, FR-R.1a).
- **A report about a claim nobody could split into products** may have what is still unclear,
  what the merchant is asked for, and its email reworked. It can never be given an amount,
  because nothing on it was ever priced — so where the representative settles the split, the
  claim is investigated instead, which is the only honest route from "we cannot tell which
  product" to "here is what to pay" (FR-1a.4).
- **A report for a claim the quick checks turned away** may have only its merchant email
  reworded. Its verdict is arithmetic and no message can overturn one (FR-0.6, FR-R.8).

**Every path produces one report**, because a claim has one (FR-2.9b). Where a message causes
the claim to be investigated, the findings become the next version of the very report the
message was written on, so the conversation that led there stays attached to them (FR-R.13).

**Nothing here sends anything or moves any money**, whichever path a message takes. The agent
holds the investigation's read-only tools and no others (FR-R.6, FR-3.1).

**Nothing here raises for anything that can happen to a claim.** A model that cannot be
reached, ShipBob failing, a run that used up its steps: each comes back as a reply saying so,
with the report unchanged, because a representative must be left with something to act on
rather than an error page (NFR-4).
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel

from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.precedent_context import precedent_for_claim
from claim_agent.agent.prompts import EarlierExchange
from claim_agent.agent.revise import (
    ClaimFindingsRevision,
    ClaimRevision,
    ReportUnderReview,
    rework_claim_findings,
    rework_claim_report,
    rework_screening_report,
)
from claim_agent.agent.run import investigate_claim
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
) -> Report:
    """Give a representative's message to the agent, and write down what came back.

    Args:
        parked: The report as it stands, with their message already recorded on it.
        feedback: What they said, in their own words, kept exactly as written.
        at: When this is happening. Handed in rather than read from a clock, so the same
            message writes the same version twice (NFR-1).
        shipbob: Reads the case, its parcel and its order again.
        evidence: Reads the claim's images and prices the shipment.
        fetcher: Downloads an image so a model can look at it.
        models: A way to build the models, asked for only once there is something to answer.
        memory: What a representative has corrected for this merchant, read again when a claim
            is investigated afresh.
        precedent_store: The closed claims this service has handled (FR-S.5).
        policy: The thresholds this claim is judged by (FR-0.7).

    Returns:
        The next version of the report. Never raises for anything that can happen to a claim.
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
            evidence=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            shipbob=shipbob,
            memory=memory,
            precedent_store=precedent_store,
            policy=policy,
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
) -> ClaimFindingsRevision | ClaimRevision:
    """Put the message to the agent, in the shape this kind of report calls for.

    The three shapes are genuinely different questions, which is why they are three prompts
    rather than one with branches in it: what an investigated claim's report may become, what
    an unsettled claim may become, and what a stopped claim may become have almost nothing in
    common.

    `chat` is only used by the findings rework, which runs the tool-use loop. The other two ask
    one question and hold no tools, because there is nothing they could look at that would
    change their answer.
    """
    content = parked.content

    if isinstance(content, InvestigationReportContent):
        return await rework_claim_findings(
            under_review=ReportUnderReview(
                lines=content.lines,
                context=content.context,
                attachments=content.attachments,
                recommendation=content.outcome.recommendation,
                amount=content.amount,
                evidence=content.evidence,
                assessments=content.assessments,
                concerns=content.concerns,
                drafted_email=parked.drafted_email,
                conversation=what_has_been_said(parked),
            ),
            feedback=feedback,
            record=record,
            evidence_client=evidence,
            fetcher=fetcher,
            chat=chat,
            structured=structured,
            events=EventStream(),
            policy=policy,
            precedent=precedent_for_claim(
                store=precedent_store,
                case=record.case,
                lines=content.lines,
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
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    chat: BaseChatModel,
    structured: StructuredModel,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> Report:
    """Look into the products a representative just named, and nothing else (FR-1a.4).

    **This is what a representative naming a product should cost: one pass.** The heavy
    alternative — investigating the whole claim again — re-reads every image, re-splits the
    claim and re-judges everything, and on a claim nobody could split it very often comes back
    unable to split it a second time. A representative who has just answered that exact
    question should not be made to wait for the system to fail at it again.

    So their answer is turned straight into claim lines, matched against the order the way the
    split would have matched them, and the claim is investigated with all of them in hand.
    Their instruction travels with it: if they said to pay the claim, the run comes back
    approved, with the figure, because the rules that would withhold it encode the agent's
    uncertainty and they have just corrected it.

    The findings become this report's next version, so the conversation that produced them
    stays attached (FR-R.13).
    """
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
        events=EventStream(),
        policy=policy,
        precedent=precedent_for_claim(
            store=precedent_store, case=record.case, lines=lines, policy=policy
        ),
    )

    logger.info(
        "settled_products_looked_into",
        case_id=parked.case_id,
        named=len(lines),
        reworked=looked_into.reworked,
    )

    if looked_into.findings is None:
        # The run could not answer. Their message is still recorded and answered, and the
        # report keeps the clarification it had, so they can try again (NFR-4).
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


def _nothing_established_yet(
    lines: Sequence[ClaimLine], parked: Report, *, ambiguity: str | None
) -> ReportUnderReview:
    """The claim to look into, with an honest account of what is known about it: nothing.

    A claim nobody could split was never investigated, so there are no findings to carry
    forward and no figure to start from. Saying that plainly is better than seeding the run
    with a blank report that looks like one somebody produced — the run reads what it is given
    as a record of what was seen, and there is nothing to have seen.
    """
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
) -> Report:
    """Investigate the claim again, because the representative asked for it.

    This is the slow route from a claim nobody could divide into products to a report somebody
    can approve. It is a real investigation, not a rewording: the evidence is read again, the
    claim is split again, and the products are judged on what is actually in the photographs —
    which is the only way a figure can exist at all (FR-1.21).

    **What the representative said reaches it as a correction against the merchant**, written
    the moment they sent the report back (FR-R.14), and read back here as starting context
    (FR-0.5). So the split is settled by their words without any new path being invented for
    them: the same channel that improves the merchant's *next* claim improves this one.

    A claim that fails the quick checks on the way through is possible in principle — the
    thresholds can change between one screening and the next (FR-0.7) — and produces nothing
    new, so the report is carried through with the agent's reply and nothing else.

    Returns:
        The report's next version, carrying whatever the investigation established.
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
        return build_revised_report(parked, answered, feedback=feedback, at=at, reinvestigated=True)

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
) -> Report:
    """Make freshly investigated findings the next version of the report they replace.

    **Writing them as version 1 instead would be the destructive mistake.** Every build
    produces a version 1 under the claim's own report name, and writing that would land on top
    of the version the representative was looking at, taking its conversation and the record of
    what has already been decided on it with it (FR-R.13, FR-C.1).

    So the version, the conversation and the review history come from the report that was sent
    back, and everything the investigation established comes from the build. The two halves are
    copied together, because the report refuses to hold a recommendation that disagrees with
    its own content.
    """
    revised = build_revised_report(parked, revision, feedback=feedback, at=at, reinvestigated=True)
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
    """One sentence saying what investigating the claim actually turned up.

    **The agent's reply is written before the investigation runs**, so on its own it can only
    say what is about to happen. Left at that, a representative reads "I am investigating this
    again", waits, and then has to work out from the report whether anything came of it —
    which is exactly what made the first version of this read as broken.

    So the outcome is added afterwards, by code, because code is the only thing that knows it.
    """
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
    """The next version of a report that nothing could change, carrying what was said.

    Used where the agent was never reached at all. The report keeps every finding it had and
    the representative is told why, so they can send it back again or decide on it as it
    stands (NFR-4).
    """
    return build_revised_report(parked, ClaimRevision(reply=said), feedback=feedback, at=at)


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
