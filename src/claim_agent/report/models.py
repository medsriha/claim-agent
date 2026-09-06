from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from claim_agent.domain.assessment import Assessment, Confidence
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.decision import DecisionStage, Proposal, RepAction
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Attachment, DraftedEmail, TerminalReason, UtcDatetime
from claim_agent.domain.outcome import OutcomeDecision, Recommendation
from claim_agent.domain.reimbursement import AmountDerivation
from claim_agent.preflight.models import ClaimContext, GateResult


class ReportState(StrEnum):
    """Where a report has got to in its review (FR-2.8, FR-2.9)."""

    AWAITING_REVIEW = "awaiting_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


class EmailWording(BaseModel):
    """The subject and body a representative supplied while approving an email."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    body: str


class InvestigationReportContent(BaseModel):
    """Settled findings for one claim, ready for a UI to lay out (FR-1b.1, FR-2.9a).

    `lines` is every damaged product the claim covers. There is one outcome, one amount and
    one email across all of them; what each product contributed to the figure is in
    `amount.components` (FR-1b.4).

    `finding_summary` keeps the investigation's concise decision basis separate from the
    itemized merchant request. It is optional so reports stored before this field was added
    remain readable; their UI can fall back to the deterministic outcome explanation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["investigation"] = "investigation"
    lines: tuple[ClaimLine, ...]
    context: ClaimContext
    attachments: tuple[Attachment, ...] = ()
    evidence: tuple[EvidenceFinding, ...]
    assessments: tuple[Assessment, ...]
    outcome: OutcomeDecision
    amount: AmountDerivation
    concerns: tuple[str, ...]
    requested_details: tuple[str, ...] = ()
    finding_summary: str | None = None
    corrections_considered: tuple[str, ...] = ()


class ScreeningReportContent(BaseModel):
    """The deterministic findings for a claim stopped before investigation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["screening"] = "screening"
    context: ClaimContext
    reasons: tuple[TerminalReason, ...]
    findings: tuple[str, ...]
    gates: tuple[GateResult, ...]
    requires_rep_clarification: bool


class ClarificationReportContent(BaseModel):
    """Claim-level findings when no safe product-level investigation can be produced.

    `requested_details` is populated when the merchant can settle the unclear split.
    It stays empty when the problem needs a representative instead.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["clarification"] = "clarification"
    context: ClaimContext
    attachments: tuple[Attachment, ...] = ()
    candidate_lines: tuple[ClaimLine, ...] = ()
    ambiguity: str
    concerns: tuple[str, ...]
    requested_details: tuple[str, ...] = ()


ReportContent = InvestigationReportContent | ScreeningReportContent | ClarificationReportContent


class ReportReview(BaseModel):
    """One review action, stored as data rather than appended prose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_number: int
    action: RepAction
    recommended: Proposal
    decided: Proposal
    edited_email: EmailWording | None = None
    rep_words: str | None = None
    over_the_cap_by: Decimal | None = None


class RevisionTurn(BaseModel):
    """One round of the conversation between a representative and the agent (FR-R.13).

    A representative sends a report back with a note; the agent reworks it and answers. That
    exchange is one turn, and every turn a report has been through is kept on it, oldest
    first. Together they are the record of how a decision was reached and where a person
    intervened.

    A turn that changes the report produces a new version. A question answered without changing
    the report is recorded on the current version instead, because a conversation is worth
    keeping but is not itself a new telling of the findings.

    Fields:
        turn: Which round this is, counting from 1.
        from_version: The version of the report the representative was looking at when they
            wrote the note. Reading that version back is how somebody sees what they saw.
        feedback: What they said, in their own words, exactly as written.
        reply: What the agent said back to them. Where the rework did not happen, this is
            the reason it did not.
        changed: What the agent changed in response, one item each (FR-R.10).
        left_unchanged: What the note did not bear on, carried forward as it was.
        needs_reply: Whether the agent's reply asks the representative a question. It changes
            nothing about what is recommended; it says the conversation is waiting on a
            person rather than finished.
        reworked: Whether anything about the report actually changed. False covers a run that
            could not be completed and an answer that was only an answer — a representative
            asking a question and being told something does not make the report different.
        reinvestigated: Whether this round caused the claim to be investigated again. That
            happens when a representative settles what an unsettled claim is for, and the
            findings become this report's own next version (FR-1a.4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: int
    from_version: int
    feedback: str
    reply: str
    changed: tuple[str, ...] = ()
    left_unchanged: tuple[str, ...] = ()
    needs_reply: bool = False
    reworked: bool = True
    reinvestigated: bool = False


class Report(BaseModel):
    """The canonical structured handoff and its review state.

    One report per claim, covering every damaged product on it (FR-1b.1, FR-2.9b).

    `content` is everything a UI needs to construct the report. The scalar fields beside it
    support claim lists, review actions, and analysis without making those callers understand
    the complete content shape. `drafted_email` is a single structured field so it can be
    rendered and edited exactly once.

    `product_names` is every damaged product the claim covers, in the order the investigation
    established them, and empty for a claim that names none — one the quick checks stopped, or
    one nobody could split. It is the summary of `content`; the claim lines themselves, with
    their prices and how each matched the order, are inside it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    version: int
    case_id: str
    product_names: tuple[str, ...]
    account_name: str | None
    user_id: str | None
    stage: DecisionStage
    state: ReportState
    recommendation: Recommendation | None
    amount_usd: Decimal | None
    confidence: Confidence | None
    carrier: str | None
    defect_type: str | None
    damage_type: str | None
    order_value_usd: Decimal | None
    decided: Proposal | None
    decisions_taken: int
    drafted_email: DraftedEmail | None
    content: ReportContent
    reviews: tuple[ReportReview, ...] = ()
    revisions: tuple[RevisionTurn, ...] = ()
    created_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def _finish_legacy_approval_email(cls, value: object) -> object:
        """Resolve old stored amount markers from the report's already-capped amount."""
        if not isinstance(value, dict):
            return value
        recommendation = value.get("recommendation")
        amount = value.get("amount_usd")
        email_value = value.get("drafted_email")
        if recommendation not in (
            Recommendation.APPROVE,
            Recommendation.APPROVE_HIGH_VALUE,
        ):
            return value
        if amount is None or email_value is None:
            return value

        email = (
            email_value
            if isinstance(email_value, DraftedEmail)
            else DraftedEmail.model_validate(email_value)
        )
        if "{{amount}}" not in email.subject and "{{amount}}" not in email.body:
            return value

        resolved = dict(value)
        resolved["drafted_email"] = email.with_approved_amount(Decimal(str(amount)))
        return resolved

    @model_validator(mode="after")
    def _must_be_internally_consistent(self) -> Self:
        """Refuse a report whose metadata and structured content tell different stories."""
        if self.stage is DecisionStage.SCREENING:
            if not isinstance(self.content, ScreeningReportContent):
                raise ValueError("A screening report needs screening content.")
            if self.product_names:
                raise ValueError("A claim stopped by the quick checks has no damaged product.")
            if self.recommendation is not None or self.amount_usd is not None:
                raise ValueError("A claim stopped by the quick checks recommends nothing.")
            if self.content.requires_rep_clarification and self.drafted_email is not None:
                raise ValueError("A representative clarification request must not carry an email.")
            if not self.content.requires_rep_clarification and self.drafted_email is None:
                raise ValueError("A merchant-facing screening report needs an email draft.")
        elif isinstance(self.content, InvestigationReportContent):
            if not self.product_names:
                raise ValueError("An investigated report has to name what was damaged.")
            if self.product_names != tuple(line.product_name for line in self.content.lines):
                raise ValueError("The report and its content must name the same products.")
            if self.recommendation is not self.content.outcome.recommendation:
                raise ValueError("The report and its content must carry the same recommendation.")
            expected_amount = (
                self.content.amount.amount_usd
                if self.recommendation is not None and self.recommendation.is_approval
                else None
            )
            if self.amount_usd != expected_amount:
                raise ValueError("The report and its content must carry the same amount.")
        else:
            if not isinstance(self.content, ClarificationReportContent):
                raise ValueError(
                    "An investigated report needs investigation or clarification content."
                )
            if self.product_names:
                raise ValueError("A claim-level clarification must not invent a settled product.")
            if self.recommendation not in (
                Recommendation.REQUEST_INFO,
                Recommendation.REQUEST_REP_CLARIFICATION,
            ):
                raise ValueError(
                    "An ambiguous claim must request merchant information or representative "
                    "clarification."
                )
            if self.amount_usd is not None:
                raise ValueError("A clarification request cannot carry an approved amount.")

        if self.recommendation is Recommendation.REQUEST_REP_CLARIFICATION:
            if self.drafted_email is not None:
                raise ValueError("A representative clarification request must not carry an email.")
        elif (
            self.recommendation
            in (
                Recommendation.APPROVE,
                Recommendation.APPROVE_HIGH_VALUE,
                Recommendation.REQUEST_INFO,
            )
            and self.drafted_email is None
        ):
            raise ValueError("An approval or merchant information request needs an email draft.")
        if self.drafted_email is not None and (
            "{{amount}}" in self.drafted_email.subject or "{{amount}}" in self.drafted_email.body
        ):
            raise ValueError("A finished merchant email cannot contain an amount placeholder.")
        if self.recommendation is Recommendation.REQUEST_INFO:
            requested_details = (
                self.content.requested_details
                if isinstance(
                    self.content, (InvestigationReportContent, ClarificationReportContent)
                )
                else ()
            )
            if not requested_details:
                raise ValueError(
                    "A merchant information request must name the specific details needed."
                )

        if self.decided is not None and self.state is not ReportState.APPROVED:
            raise ValueError("Only an approved report says what the representative settled on.")
        if self.version < 1:
            raise ValueError("A report's first version is 1.")
        if self.decisions_taken < 0:
            raise ValueError("A report cannot have had fewer than no decisions taken on it.")
        if self.decisions_taken != len(self.reviews):
            raise ValueError("Every review action must have one structured review entry.")
        for position, turn in enumerate(self.revisions, start=1):
            # The conversation is the record of how a decision was reached (FR-R.13), so it has
            # to be readable in the order it happened. A turn out of sequence, or one claiming
            # to answer a version that did not exist when it was written, is a garbled record
            # rather than a surprising one.
            if turn.turn != position:
                raise ValueError("The rounds of a conversation must be numbered in order.")
            if not 1 <= turn.from_version <= self.version:
                raise ValueError("A round must answer this version of the report or one before it.")
        return self


class ClaimView(BaseModel):
    """The report on one claim, if it has one yet (FR-2.9b).

    A claim has at most one report, so this holds none or one. It is kept as a list rather
    than a single optional field because "nobody has asked for this claim to be investigated"
    is an ordinary answer, and an empty list says it without a caller having to read a null.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    reports: tuple[Report, ...] = ()
