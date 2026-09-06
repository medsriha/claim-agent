from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from claim_agent.agent.budget import BudgetSnapshot
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.decision import Confidence, DecisionStage, Proposal, RepAction
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
    """Settled findings for one claim, ready for a UI to lay out (FR-1b.1, FR-2.9a)."""

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
    thread_id: str | None = None
    """The conversation thread the investigation wrote to, so a rework can continue it (FR-R.2)."""
    prompt_version: str | None = None
    """Which edition of the wording produced these findings (NFR-1, NFR-5)."""
    model: str | None = None
    """Which model produced them."""
    budget: BudgetSnapshot | None = None
    """What the run cost: steps, images, model calls and tokens (NFR-3)."""


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
    """Claim-level findings when no safe product-level investigation can be produced."""

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
    """One round of the conversation between a representative and the agent (FR-R.13)."""

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
    """The canonical structured handoff and its review state."""

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

        if (
            self.recommendation
            in (
                Recommendation.APPROVE,
                Recommendation.APPROVE_HIGH_VALUE,
                Recommendation.REQUEST_INFO,
            )
            and self.drafted_email is None
        ):
            raise ValueError("An approval or merchant information request needs an email draft.")
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
            if turn.turn != position:
                raise ValueError("The rounds of a conversation must be numbered in order.")
            if not 1 <= turn.from_version <= self.version:
                raise ValueError("A round must answer this version of the report or one before it.")
        return self


class ClaimView(BaseModel):
    """The report on one claim, if it has one yet (FR-2.9b)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    reports: tuple[Report, ...] = ()
