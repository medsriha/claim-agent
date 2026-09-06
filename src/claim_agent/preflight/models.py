from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from claim_agent.domain.models import (
    Case,
    DraftedEmail,
    GateName,
    MerchantCorrection,
    Order,
    Shipment,
    TerminalReason,
    UtcDatetime,
    Verdict,
)


class DeliveryDate(BaseModel):
    """When the parcel was delivered, and which record that date was taken from."""

    value: UtcDatetime | None
    source: Literal["case", "shipment", "none"]
    case_value: UtcDatetime | None
    shipment_value: UtcDatetime | None

    @property
    def sources_disagree(self) -> bool:
        """True when both records carry a delivery date and the two do not match."""
        if self.case_value is None or self.shipment_value is None:
            return False
        return self.case_value != self.shipment_value


class GateResult(BaseModel):
    """The outcome of one of the four eligibility checks (FR-0.2)."""

    gate: GateName
    passed: bool
    reason: TerminalReason | None = None
    explanation: str
    observed: dict[str, str]


class CaseRecord(BaseModel):
    """Everything the pre-flight screen read about a claim, gathered in one place (FR-0.1)."""

    case: Case
    shipment: Shipment | None
    order: Order | None


class ClaimContext(BaseModel):
    """The facts worked out up front so the investigation does not have to (FR-0.5)."""

    order_value_usd: Decimal | None
    is_high_value: bool
    days_since_delivery: int | None
    delivered_date: UtcDatetime | None
    merchant_corrections: tuple[MerchantCorrection, ...] = ()


class TerminalReport(BaseModel):
    """What a rep receives when a claim cannot be processed at all (FR-0.4)."""

    case_id: str
    account_name: str | None
    user_id: str | None
    reasons: tuple[TerminalReason, ...]
    findings: tuple[str, ...]
    gates: tuple[GateResult, ...]
    context: ClaimContext
    drafted_email: DraftedEmail | None
    requires_rep_clarification: bool
    requires_rep_approval: Literal[True] = True

    @model_validator(mode="after")
    def _must_give_the_rep_something_to_do(self) -> Self:
        """Refuse a write-up that leaves a rep holding nothing, or holding the wrong thing."""
        insured = TerminalReason.SHIPMENT_INSURED in self.reasons
        if insured != self.requires_rep_clarification:
            raise ValueError(
                "requires_rep_clarification has to be true exactly when the shipment was insured."
            )

        tellable = [
            reason for reason in self.reasons if reason is not TerminalReason.SHIPMENT_INSURED
        ]
        if insured and self.drafted_email is not None:
            raise ValueError("A representative clarification request must not carry an email.")
        if not insured and tellable and self.drafted_email is None:
            raise ValueError("A claim with a reason the merchant can be told needs an email.")
        if not insured and not tellable and self.drafted_email is not None:
            raise ValueError("A claim with nothing to tell the merchant must not carry an email.")
        return self


class PreflightResult(BaseModel):
    """The complete outcome of the pre-flight screen for one claim (FR-0.3)."""

    case_id: str
    verdict: Verdict
    terminal_reasons: tuple[TerminalReason, ...] = ()
    gates: tuple[GateResult, ...]
    record: CaseRecord
    context: ClaimContext
    report: TerminalReport | None = None
    evaluated_at: UtcDatetime

    @model_validator(mode="after")
    def _verdict_must_match_its_evidence(self) -> Self:
        """Refuse to exist in a state the rest of the layer could not make sense of."""
        if self.verdict is Verdict.TERMINAL:
            if not self.terminal_reasons:
                raise ValueError("A terminal verdict has to give at least one reason.")
            if self.report is None:
                raise ValueError("A terminal verdict has to carry a report for the rep.")
            return self
        if self.terminal_reasons:
            raise ValueError("A proceed verdict must not carry terminal reasons.")
        if self.report is not None:
            raise ValueError("A proceed verdict must not carry a terminal report.")
        return self
