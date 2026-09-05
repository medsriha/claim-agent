"""Reading the reports a representative decides from, and acting on one.

Everything an investigation established used to live only in the reply to the request that asked
for it. These routes are the other half: a claim's reports can be fetched back, read one at a
time, approved, or sent back with a note (FR-2.8, FR-2.9b, FR-R.13).

**Sending one back is a conversation, not a filing cabinet.** Whatever a representative types is
recorded, remembered against the merchant, and then given to the agent, which answers them
directly and reworks whatever the message bears on. The result is the next version of the
report, awaiting review like any other (FR-R.1 to FR-R.14).

**Every message gets an answer, whatever the report is.** What the agent may *change* differs —
a stopped claim's verdict is not open to it — but no message is turned away by this route with
wording of its own. Which path a message takes is decided in `claim_agent.report.conversation`,
which is also where the reply comes from.

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

from claim_agent.api.deps import (
    DecisionStoreDep,
    EvidenceClientDep,
    ImageFetcherDep,
    MerchantMemoryDep,
    ModelsDep,
    PolicyDep,
    PrecedentStoreDep,
    ReportStoreDep,
    ShipBobClientDep,
)
from claim_agent.domain.models import MerchantCorrection
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import InvalidRequestError, NotFoundError, StorageError
from claim_agent.observability import get_logger
from claim_agent.report.build import siblings_of
from claim_agent.report.conversation import answer_the_representative
from claim_agent.report.models import (
    ClaimView,
    EmailWording,
    Report,
    ReportForReview,
)
from claim_agent.report.review import ReviewOutcome, approve, send_back
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.report_store import ReportStore

logger = get_logger(__name__)

router = APIRouter(tags=["reports"])


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
    the merchant, so their next claim starts knowing about it — and so a claim investigated
    again reads it as context (FR-R.14, FR-0.5). Then the agent is given the message and
    answers, and what comes back is filed as the next version, awaiting review like any other
    (FR-R.9, FR-R.13).

    **Every message is answered.** There is no report this route refuses to pass a message on
    about. What the agent may change differs by report — a claim the quick checks stopped keeps
    its verdict whatever anybody says (FR-R.8) — but the representative always gets a reply.

    **A message can cause a fresh investigation**, when it settles what an unsettled claim is
    for or asks for one outright. That writes a report per damaged product beside this one; the
    reply says so, and the claim's reports are where they appear (FR-1a.4, FR-2.9b).

    **The representative waits while that happens.** Answering takes a model call or several,
    and this answers in one piece rather than narrating itself.

    **Nothing here sends anything or moves any money**, in either direction. The agent holds
    the investigation's read-only tools and no others (FR-R.6, FR-3.1).

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
        back, and what it changed. **An answer that changed nothing still produces a version**
        — with the previous findings unchanged and the reply on it — because a representative
        must never be left with an error page instead of the work they were deciding on, and
        because being answered is worth recording even when nothing moved (NFR-4).

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

    written = await answer_the_representative(
        parked,
        feedback=sending_back.feedback,
        at=datetime.now(UTC),
        reports=reports,
        shipbob=shipbob,
        evidence=evidence,
        fetcher=fetcher,
        models=models,
        memory=memory,
        precedent_store=precedent_store,
        policy=policy,
    )
    for produced in written.alongside:
        reports.record(produced)
    reports.record(written.report)

    logger.info(
        "representative_was_answered",
        case_id=written.report.case_id,
        report_id=written.report.report_id,
        version=written.report.version,
        reworked=written.report.revisions[-1].reworked,
        produced=len(written.alongside),
    )
    return written.report


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

    **Written before the agent is asked, and that order is deliberate.** A claim being
    investigated again reads these corrections as starting context (FR-0.5), so a representative
    settling which products were damaged has their answer reach that investigation through the
    channel that already exists rather than through one invented for it.

    Nothing is stored for a claim that names no merchant, because there is nothing to file it
    against; merchants are identified by the account number, which is stable, and never by the
    brand name, which is display text.

    A store that cannot be written is logged and otherwise ignored. Losing a note against a
    merchant is worth less than losing the answer the representative is waiting for.
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
