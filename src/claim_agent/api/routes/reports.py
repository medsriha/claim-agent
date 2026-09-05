"""Reading the reports a representative decides from, and acting on one.

Everything an investigation established used to live only in the reply to the request that asked
for it. These routes are the other half: a claim's reports can be fetched back, read one at a
time, approved, or sent back with a note (FR-2.8, FR-2.9b, FR-R.13).

**Sending one back is a conversation, not a filing cabinet.** The note is recorded, remembered
against the merchant, and then given to the same agent that investigated the product, which
reworks the report and the merchant's email around it and answers the representative directly.
The result is the next version of the report, awaiting review like any other (FR-R.1 to FR-R.14).

**Nothing here sends anything or moves any money.** Approving records that a person accepted a
recommendation. The stage that would act on that acceptance does not exist, so an approval today
stops at being written down — which is exactly the separation FR-C.1 asks for, and what lets a
decision survive a send that later fails (FR-3.1, FR-3.6). The agent that does the reworking
holds only the investigation's read-only tools (FR-R.6).

**No money passes through a number.** A figure a representative chooses arrives as text and is
read into an exact decimal, the same way a price does when past claims are searched. A JSON
number would become a floating point value on the way in, where cents drift (FR-1.21).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.precedent_context import precedent_for_line
from claim_agent.agent.prompts import EarlierExchange
from claim_agent.agent.revise import LineRevision, ReportUnderReview, rework_line
from claim_agent.api.deps import (
    DecisionStoreDep,
    EvidenceClientDep,
    ImageFetcherDep,
    MerchantMemoryDep,
    ModelsDep,
    ModelsFor,
    PolicyDep,
    PrecedentStoreDep,
    ReportStoreDep,
    ShipBobClientDep,
)
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import SHARED_EVIDENCE
from claim_agent.domain.models import MerchantCorrection
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ClaimAgentError, InvalidRequestError, NotFoundError, StorageError
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.preflight.gather import gather_case_record
from claim_agent.report.build import build_revised_report, siblings_of
from claim_agent.report.models import (
    ClaimView,
    EmailWording,
    InvestigationReportContent,
    Report,
    ReportForReview,
)
from claim_agent.report.review import ReviewOutcome, approve, send_back
from claim_agent.shipbob.client import ShipBobClient
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.precedent_store import PrecedentStore
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)

router = APIRouter(tags=["reports"])

_NOTHING_TO_REWORK = {
    "screening": (
        "This claim was stopped by the eligibility checks, which are fixed rules rather than "
        "judgements, so there is no investigation to rework and feedback cannot overturn the "
        "verdict. The note has been recorded. Approve the report to accept it as it stands, or "
        "take the claim up outside this system."
    ),
    "clarification": (
        "It was never established which product this claim is for, so there is no product "
        "report to rework. The note has been recorded. Investigating the claim again is what "
        "would settle the split."
    ),
}
"""What a representative is told when the report they sent back cannot be reworked.

Only two kinds of report cannot be: one for a claim the quick checks turned away, and one for a
claim whose split was never settled. Neither has an investigation behind it to redo, and in the
first the verdict came from rules that FR-R.8 says feedback may not overturn.

Each sentence says what was recorded and what the representative can do instead, because being
told only that nothing happened leaves somebody stuck (NFR-4).
"""


class Approval(BaseModel):
    """What a representative sends when they accept a report (FR-2.8, action 1).

    Every field is optional, because approving a report exactly as it stands is the ordinary case
    and should need nothing said about it.

    `amount_usd` is **text, never a number**. Written as digits with at most two decimal places
    and no currency symbol, such as `"31.20"`. A JSON number would be read as a floating point
    value, where `0.10` cannot be held exactly and cents drift (FR-1.21).

    A figure over the cap is accepted. The cap limits what the *system* may recommend, and no
    requirement says a person may not exceed it — so the decision is recorded as it was made and
    the report says plainly that it went over (FR-1.20, FR-R.8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation | None = None
    amount_usd: str | None = None
    email: EmailWording | None = None
    rep_words: str | None = None
    rep_minutes: int = 0


class SendBack(BaseModel):
    """What a representative sends when a report is not usable as it arrived (FR-2.8, action 2).

    `feedback` is kept exactly as written. It is the whole input to the reworking, and to what is
    remembered against the merchant afterwards, and paraphrasing it here would change both
    (FR-R.3, FR-C.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feedback: str
    rep_minutes: int = 0


@router.get("/cases/{case_id}/reports", summary="Every report on one claim")
async def read_claim(case_id: str, reports: ReportStoreDep) -> ClaimView:
    """List a claim's reports, so a representative works from a case (FR-2.9b).

    One row per damaged product, or a single row for a claim the quick checks stopped before it
    ever had products in it. A view over the reports and nothing more: approving still happens one
    product at a time, on the report itself.

    Args:
        case_id: The claim, such as `CASE-1001`.
        reports: Where reports are kept.

    Returns:
        The claim's reports, each at the version in force. **An empty list means nobody has asked
        for this claim to be investigated**, which is an ordinary answer — a claim whose reports
        could not be read fails instead, so the two can never be mistaken for one another.
    """
    return reports.for_case(case_id)


@router.get("/reports/{report_id}", summary="Read one report")
async def read_report(
    report_id: str, reports: ReportStoreDep, version: int | None = None
) -> ReportForReview:
    """Read one report, with the other products on its claim beside it (FR-2.9a, FR-R.13).

    Args:
        report_id: Which report.
        reports: Where reports are kept.
        version: Which telling of it. Left out — the usual case — reads the one in force. Naming
            one reads back what a representative was looking at earlier, which is the record of
            how a decision was reached (FR-R.13).

    Returns:
        The report, and one row per other damaged product on the same claim. Those rows are looked
        up now rather than stored with the report, because a sibling's review state changes the
        moment somebody approves it.

    Raises:
        NotFoundError: There is no such report, or no such version of it.
    """
    report = _the_report(reports, report_id, version=version)
    return ReportForReview(
        report=report, siblings=siblings_of(report, reports.for_case(report.case_id))
    )


@router.post("/reports/{report_id}/approve", summary="Approve a report")
async def approve_report(
    report_id: str,
    approval: Approval,
    reports: ReportStoreDep,
    decisions: DecisionStoreDep,
    policy: PolicyDep,
) -> Report:
    """Accept a report, as it stands or after changing it (FR-2.8, FR-2.9, FR-C.1).

    This is the only way a report leaves the review. Nothing else reaches an approval: no time
    limit, no level of confidence, and no number of rounds.

    **Approving sends nothing and pays nothing.** It records that a person accepted a
    recommendation, and the stage that would act on that does not exist (FR-3.1).

    Args:
        report_id: Which report.
        approval: What the representative settled on, and anything they said.
        reports: Where reports are kept.
        decisions: Where what a representative decided is recorded (FR-C.1).
        policy: Read for the most the system may recommend on one claim (FR-0.7).

    Returns:
        The approved report, carrying what was advised, what was settled on, and a section saying
        what the representative did.

    Raises:
        NotFoundError: There is no such report.
        InvalidRequestError: A figure was sent that is not an amount written as text.
        ConflictError: The report is already approved and this differs from what was approved.
    """
    report = _the_report(reports, report_id)
    outcome = approve(
        report,
        decided_outcome=approval.outcome,
        decided_amount_usd=_amount(approval.amount_usd),
        edited_email=approval.email,
        rep_words=approval.rep_words,
        rep_minutes=approval.rep_minutes,
        policy=policy,
        at=datetime.now(UTC),
    )
    return _write_down(outcome, reports=reports, decisions=decisions)


@router.post("/reports/{report_id}/send-back", summary="Send a report back with feedback")
async def send_report_back(
    report_id: str,
    sending_back: SendBack,
    reports: ReportStoreDep,
    decisions: DecisionStoreDep,
    shipbob: ShipBobClientDep,
    evidence: EvidenceClientDep,
    fetcher: ImageFetcherDep,
    models: ModelsDep,
    memory: MerchantMemoryDep,
    precedent_store: PrecedentStoreDep,
    policy: PolicyDep,
) -> Report:
    """Send a report back with a note, and get it reworked around that note (FR-2.8, FR-R.1).

    Three things happen, in this order, and the order matters. What the representative said is
    recorded as a decision, so it survives whatever follows (FR-C.1). It is remembered against
    the merchant, so their next claim starts knowing about it (FR-R.14). Then the same agent
    that investigated the product is asked to rework its report around it, and what comes back
    is filed as the next version, awaiting review like any other (FR-R.9, FR-R.13).

    **The representative waits while that happens.** A rework takes a model call or several,
    and this answers in one piece rather than narrating itself.

    **Nothing here sends anything or moves any money**, in either direction. The agent doing
    the reworking holds the investigation's read-only tools and no others (FR-R.6, FR-3.1).

    Args:
        report_id: Which report.
        sending_back: What is wrong or missing, in the representative's own words.
        reports: Where reports are kept, and where the new version goes.
        decisions: Where what a representative decided is recorded (FR-C.1).
        shipbob: Reads the case, its parcel and its order again, so the rework is built from
            ShipBob's records rather than from a copy stored months ago.
        evidence: Reads the claim's images and prices the shipment.
        fetcher: Downloads an image so a model can look at it.
        models: A way to build the models, asked for only once there is a rework to run.
        memory: What a representative has corrected for this merchant, which this adds to.
        precedent_store: The closed claims this service has handled, so a reconsidered figure
            is judged the way comparable claims actually were (FR-R.7, FR-S.6).
        policy: The thresholds the rework is judged by (FR-0.7).

    Returns:
        The next version of the report, carrying what was said about it, what the agent said
        back, and what it changed. **A rework that could not be run still produces a version**
        — with the previous findings unchanged and a reply saying why — because a
        representative must never be left with an error page instead of the work they were
        deciding on (NFR-4).

    Raises:
        NotFoundError: There is no such report.
        ConflictError: The report has already been approved, and an approval is final.
    """
    report = _the_report(reports, report_id)
    outcome = send_back(
        report,
        feedback=sending_back.feedback,
        rep_minutes=sending_back.rep_minutes,
        at=datetime.now(UTC),
    )
    parked = _write_down(outcome, reports=reports, decisions=decisions)
    _remember_against_the_merchant(memory, parked, feedback=sending_back.feedback)

    revision = await _rework(
        parked,
        feedback=sending_back.feedback,
        reports=reports,
        shipbob=shipbob,
        evidence=evidence,
        fetcher=fetcher,
        models=models,
        precedent_store=precedent_store,
        policy=policy,
    )
    revised = build_revised_report(
        parked, revision, feedback=sending_back.feedback, at=datetime.now(UTC)
    )
    reports.record(revised)
    logger.info(
        "report_revised",
        case_id=revised.case_id,
        claim_line_id=revised.claim_line_id,
        report_id=revised.report_id,
        version=revised.version,
        reworked=revision.reworked,
    )
    return revised


async def _rework(
    report: Report,
    *,
    feedback: str,
    reports: ReportStore,
    shipbob: ShipBobClient,
    evidence: EvidenceClient,
    fetcher: ImageFetcher,
    models: ModelsFor,
    precedent_store: PrecedentStore,
    policy: Policy,
) -> LineRevision:
    """Gather what a rework needs and run it, or say plainly why it did not run (FR-R.2).

    Everything that can go wrong before the agent is asked anything comes back as a rework that
    did not happen, carrying a sentence a representative can act on. None of it raises: the note
    has already been recorded, and failing the request now would hide it (NFR-4).

    Three things stop a rework before it starts. A claim the quick checks turned away has no
    investigation to redo, and its verdict came from fixed rules that feedback may not overturn
    (FR-R.8). A claim whose split was never settled has no product to rework. And a case ShipBob
    will not give us cannot be reworked against anything.
    """
    if not isinstance(report.content, InvestigationReportContent):
        return LineRevision(investigation=None, reply=_NOTHING_TO_REWORK[report.content.kind])

    try:
        record = await gather_case_record(report.case_id, shipbob)
    except ClaimAgentError as failure:
        logger.warning(
            "rework_could_not_read_the_case",
            case_id=report.case_id,
            failure=type(failure).__name__,
        )
        return LineRevision(
            investigation=None,
            reply=(
                "This claim's records could not be read from ShipBob, so the report could not "
                "be reworked and nothing in it has changed. Send it back again to try once more."
            ),
        )

    try:
        chat, structured = models()
    except ClaimAgentError as failure:
        logger.warning(
            "rework_needs_a_model_it_cannot_have",
            case_id=report.case_id,
            failure=type(failure).__name__,
        )
        return LineRevision(
            investigation=None,
            reply=(
                "The model that would rework this report could not be reached, so nothing in "
                "it has changed. Send it back again to try once more."
            ),
        )

    content = report.content
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
            drafted_email=report.drafted_email,
            conversation=_what_has_been_said(report),
            siblings=_the_other_products(report, reports),
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
            # The three that describe the parcel, exactly as a first pass supplies them. The
            # report has settled all four by now, and handing over the fourth would make a
            # rework search on a different pattern from the investigation that preceded it —
            # so the same claim could be shown different past claims for no stated reason.
            shared_evidence=tuple(
                finding for finding in content.evidence if finding.kind in SHARED_EVIDENCE
            ),
        ),
    )


def _what_has_been_said(report: Report) -> tuple[EarlierExchange, ...]:
    """Every earlier round of this report going back and forth, oldest first (FR-R.12).

    Empty the first time, which is the usual case. From the second onwards it is what stops the
    agent undoing an earlier correction while answering a later one — the only thing that
    distinguishes one pass from the next, since it is the same agent every time.
    """
    return tuple(
        EarlierExchange(feedback=turn.feedback, reply=turn.reply, changed=turn.changed)
        for turn in report.revisions
    )


def _the_other_products(report: Report, reports: ReportStore) -> tuple[ClaimLine, ...]:
    """The claim's other damaged products, read from their own reports (FR-1b.2).

    Looked up rather than stored on the report, for the same reason the rows beside a report
    are: what the other products are is a fact about the claim now, not when this report was
    written.

    A store that cannot be read gives none rather than failing the rework. Knowing what else was
    claimed for makes a rework better informed; not knowing costs a sentence of context, and
    losing the whole rework over it would cost the representative their answer (NFR-4).
    """
    try:
        claim = reports.for_case(report.case_id)
    except StorageError:
        logger.warning("rework_could_not_read_the_other_products", case_id=report.case_id)
        return ()

    return tuple(
        other.content.line
        for other in claim.reports
        if other.report_id != report.report_id
        and isinstance(other.content, InvestigationReportContent)
    )


def _remember_against_the_merchant(
    memory: MerchantMemory, report: Report, *, feedback: str
) -> None:
    """Keep what a representative said, so the merchant's next claim starts knowing it (FR-R.14).

    Feedback is not only about the claim in hand. A representative who corrects the same thing
    on every claim from one merchant is doing work the system should have done, and this is how
    it stops having to be done twice (FR-3.8).

    Their own words are what is stored. A summary of a correction is exactly the thing FR-C.2
    warns against — "the amount was wrong" carries nothing, and paraphrasing is how a note
    becomes that.

    Nothing is stored for a claim that names no merchant, because there is nothing to file it
    against; merchants are identified by the account number, which is stable, and never by the
    brand name, which is display text.

    A store that cannot be written is logged and otherwise ignored. Losing a note against a
    merchant is worth less than losing the rework the representative is waiting for.
    """
    if report.user_id is None:
        return
    try:
        memory.record_correction(
            MerchantCorrection(
                user_id=report.user_id,
                case_id=report.case_id,
                summary=feedback,
                recorded_at=datetime.now(UTC),
            )
        )
    except StorageError:
        logger.warning(
            "correction_not_remembered", case_id=report.case_id, report_id=report.report_id
        )


def _the_report(reports: ReportStore, report_id: str, *, version: int | None = None) -> Report:
    """Fetch one report, or say plainly that there is no such thing.

    Raises:
        NotFoundError: There is no such report, or no such version of it. Never raised because
            the store could not be read — that fails with its own answer, so "no such report" and
            "we could not look" are never confused.
    """
    report = reports.get(report_id, version=version)
    if report is None:
        raise NotFoundError(f"There is no report {report_id!r}.")
    return report


def _write_down(
    outcome: ReviewOutcome, *, reports: ReportStore, decisions: DecisionStore
) -> Report:
    """Record what a representative did, then move the report on.

    **The decision is written first, and that order matters.** If the report fails to be written
    afterwards, the retry starts from a report still awaiting review, works out the very same
    decision — the name of a decision comes from what it was about and which decision on that
    report it is, so it does not change — writes over it, and moves the report on. Nothing is
    counted twice and nothing is lost (FR-C.4, FR-3.5).

    The other order cannot heal itself: a report already moved on has nothing left to re-decide,
    so a decision lost on the way would stay lost.

    `outcome.decision` is `None` when nothing happened — the same approval arriving twice — and
    there is then nothing to write.
    """
    if outcome.decision is not None:
        decisions.record(outcome.decision)
        logger.info(
            "representative_decided",
            case_id=outcome.report.case_id,
            claim_line_id=outcome.report.claim_line_id,
            report_id=outcome.report.report_id,
            action=outcome.decision.action.value,
        )
    reports.record(outcome.report)
    return outcome.report


def _amount(value: str | None) -> Decimal | None:
    """Read an amount given as text, or `None` when none was given.

    Args:
        value: An amount written out, such as `"31.20"`. `None` when the representative is not
            changing the figure, which is the ordinary case.

    Raises:
        InvalidRequestError: The text is not an amount. Answered as a 400 rather than being
            quietly treated as "no change", which would approve a figure nobody chose.
    """
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as failure:
        raise InvalidRequestError(
            "amount_usd has to be an amount written as text, such as '31.20'.",
            details={"amount_usd": value},
        ) from failure
