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
    """When the parcel was delivered, and which record that date was taken from.

    The delivery date decides whether a claim is too old (FR-0.2), and two
    records carry it: the support case and the shipment. They can hold different
    dates, so the one that was used is kept alongside both originals. A rep
    asking "why was this called too old?" can then see exactly which date the
    answer rests on (NFR-3).

    `value` is `None`, with `source` set to "none", when neither record has a
    delivery date. Nothing can be said about the claim's age in that case.
    """

    value: UtcDatetime | None
    source: Literal["case", "shipment", "none"]
    case_value: UtcDatetime | None
    shipment_value: UtcDatetime | None

    @property
    def sources_disagree(self) -> bool:
        """True when both records carry a delivery date and the two do not match.

        Worth surfacing, because the age of the claim then depends on which
        record you believe. One record simply missing its date is not a
        disagreement — there is nothing to disagree with.
        """
        if self.case_value is None or self.shipment_value is None:
            return False
        return self.case_value != self.shipment_value


class GateResult(BaseModel):
    """The outcome of one of the four eligibility checks (FR-0.2).

    `passed` being false means this check is what stopped the claim, and `reason`
    names the rule it broke; a check that passed has no reason to give.
    `explanation` is one plain sentence a rep can read without knowing the rules.
    `observed` holds every value the check actually looked at, written out as
    text, so its finding can be verified instead of taken on trust (NFR-3).
    """

    gate: GateName
    passed: bool
    reason: TerminalReason | None = None
    explanation: str
    observed: dict[str, str]


class CaseRecord(BaseModel):
    """Everything the pre-flight screen read about a claim, gathered in one place (FR-0.1).

    `shipment` and `order` are `None` when the case named none, or when the
    record could not be read. Missing is not the same as empty: a claim with no
    readable order has no value to judge, rather than a value of nothing. The
    check for missing key information is what decides whether that stops the
    claim (FR-0.2).
    """

    case: Case
    shipment: Shipment | None
    order: Order | None


class ClaimContext(BaseModel):
    """The facts worked out up front so the investigation does not have to (FR-0.5).

    `order_value_usd` is `None` when the order could not be read, which is not
    the same as an order worth nothing. `is_high_value` compares that value with
    the threshold kept in the policy file; with no value to compare it is false,
    meaning "not known to be high value" rather than "known to be ordinary".

    `days_since_delivery` is `None` when no delivery date is known.
    `merchant_corrections` are changes reps made on this merchant's earlier
    claims (FR-3.8); an empty tuple means either a merchant new to us or one
    whose claims have never needed correcting.
    """

    order_value_usd: Decimal | None
    is_high_value: bool
    days_since_delivery: int | None
    delivered_date: UtcDatetime | None
    merchant_corrections: tuple[MerchantCorrection, ...] = ()


class TerminalReport(BaseModel):
    """What a rep receives when a claim cannot be processed at all (FR-0.4).

    A claim that is ruled out is still closed with an explanation to the merchant,
    that explanation is an email, and every email waits for a rep. So a stopped
    claim skips the investigation but still produces this.

    There are two things a rep can be handed here, and each report carries exactly
    one:

    - **A drafted email**, for every reason a merchant can be told about. `None`
      when representative clarification is the next action.
    - **Representative clarification**, when the claim has to leave this automated path.
      `requires_rep_clarification` is true exactly when the shipment was insured: those
      are claimed on their insurance through a process that is not ours, so they
      are routed out for someone else to pick up rather than answered (FR-0.2).

    A claim that is both insured and, say, too old asks the representative for
    clarification and carries no email. The representative-facing action takes
    precedence over generating merchant wording.

    `reasons` lists every reason the claim was stopped, insured first when it
    applies, then in the order the email explains the rest. `findings` is one plain
    sentence for each check that failed, including the insurance check — that
    sentence is the representative clarification request note, and it is read by a rep rather than sent to
    anyone. `gates` carries all four, passed and failed alike, because knowing what
    was checked and cleared is part of being able to audit the decision (NFR-3).
    `requires_rep_approval` is fixed at true: nothing here leaves on its own.
    """

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
        """Refuse a write-up that leaves a rep holding nothing, or holding the wrong thing.

        Three ways this could go wrong, all of them mistakes in our own code rather
        than anything a merchant or ShipBob did, and all of them worth stopping here
        instead of letting a claim quietly go nowhere (NFR-4):

        - **An insured claim not marked for representative clarification request**, or a claim marked for
          representative clarification request that was never insured. The flag and the reason have to agree,
          or a claim is routed by one and explained by the other.
        - **A merchant-facing outcome with no email drafted.** That is a claim closed
          without the explanation FR-0.4 says it is owed.
        - **An email drafted for representative clarification.** That would create
          merchant wording for an action that must remain with the representative.

        Raises `ValueError`, which pydantic reports as a validation error.
        """
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
    """The complete outcome of the pre-flight screen for one claim (FR-0.3).

    Either the claim may go on to the investigation, or it is stopped and
    `report` holds the explanation a rep has to approve. `gates` carries all four
    checks either way, `record` is what was read, `context` is the groundwork
    done for whoever comes next, and `evaluated_at` is when the screen ran.

    `terminal_reasons` is empty on a claim allowed through, and in the merchant
    email's order on one that was stopped.
    """

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
        """Refuse to exist in a state the rest of the layer could not make sense of.

        A stopped claim with no reason given, or without the report the rep is
        meant to read, becomes a case that quietly disappears; a claim waved
        through while still carrying reasons to stop it is worse again (NFR-4).
        Neither can be caused by bad data from ShipBob — only by a mistake in our
        own code — so both stop here rather than travel on.

        Raises `ValueError`, which pydantic reports as a validation error.
        """
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
