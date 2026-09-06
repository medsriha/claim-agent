from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from claim_agent.domain.models import UtcDatetime
from claim_agent.domain.outcome import Recommendation

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""A self-reported certainty from 0 to 1, kept on decisions and reports for the analysis screen."""


class DecisionStage(StrEnum):
    """Which part of the system produced the thing the representative was looking at."""

    SCREENING = "screening"
    INVESTIGATION = "investigation"


class RepAction(StrEnum):
    """Which of the three review actions the representative took (FR-2.8)."""

    APPROVED = "approved"
    APPROVED_WITH_OVERRIDE = "approved_with_override"
    SENT_BACK = "sent_back"


class Proposal(BaseModel):
    """One side of the comparison: an outcome and an amount, either advised or chosen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation | None
    amount_usd: Decimal | None


class DecisionRecord(BaseModel):
    """One review action by one representative, on one claim (FR-C.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    case_id: str
    stage: DecisionStage
    report_version: int
    action: RepAction
    recommended: Proposal
    decided: Proposal
    email_edited: bool
    stated_confidence: Confidence | None
    order_value_usd: Decimal | None
    defect_type: str | None
    damage_type: str | None
    carrier: str | None
    rep_minutes: int
    rep_words: str | None
    decided_by: str | None
    decided_at: UtcDatetime

    @property
    def outcome_changed(self) -> bool:
        """Whether the representative settled on a different outcome from the one advised."""
        if self.recommended.outcome is None or self.decided.outcome is None:
            return False
        return self.recommended.outcome != self.decided.outcome

    @property
    def amount_changed(self) -> bool:
        """Whether the representative paid a different amount from the one worked out."""
        return self.recommended.amount_usd != self.decided.amount_usd

    @property
    def is_direct_approval(self) -> bool:
        """Whether this went out exactly as the system produced it, untouched."""
        return (
            self.action is RepAction.APPROVED
            and not self.outcome_changed
            and not self.amount_changed
            and not self.email_edited
        )

    @property
    def agreed_with_recommendation(self) -> bool:
        """Whether the representative accepted the advice on substance, however they worded it."""
        return self.action is not RepAction.SENT_BACK and not (
            self.outcome_changed or self.amount_changed
        )
