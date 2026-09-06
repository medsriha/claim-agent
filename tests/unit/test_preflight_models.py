from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from claim_agent.domain.models import (
    Case,
    DraftedEmail,
    GateName,
    Shipment,
    TerminalReason,
    Verdict,
)
from claim_agent.preflight.models import (
    CaseRecord,
    ClaimContext,
    DeliveryDate,
    GateResult,
    PreflightResult,
    TerminalReport,
)

DELIVERED = datetime(2026, 2, 11, 11, 36, 14, tzinfo=UTC)
FILED_AT = datetime(2026, 2, 19, 14, 20, 16, tzinfo=UTC)
DELIVERED_A_DAY_LATER = datetime(2026, 2, 12, 11, 36, 14, tzinfo=UTC)


def make_gate(gate: GateName, *, passed: bool = True) -> GateResult:
    return GateResult(
        gate=gate,
        passed=passed,
        reason=None if passed else TerminalReason.CLAIM_TOO_OLD,
        explanation="The claim was filed 8 days after delivery.",
        observed={"delivered_date": DELIVERED.isoformat(), "days_since_delivery": "8"},
    )


ALL_FOUR_GATES = tuple(make_gate(gate) for gate in GateName)


def make_context(**overrides: Any) -> ClaimContext:
    fields: dict[str, Any] = {
        "order_value_usd": Decimal("90.00"),
        "is_high_value": False,
        "days_since_delivery": 8,
        "delivered_date": DELIVERED,
    }
    fields.update(overrides)
    return ClaimContext(**fields)


def make_record() -> CaseRecord:
    return CaseRecord(
        case=Case(case_id="CASE-1001", created_date=FILED_AT),
        shipment=Shipment(shipment_id="342578703", is_insured=False),
        order=None,
    )


def make_report() -> TerminalReport:
    return TerminalReport(
        case_id="CASE-1001",
        account_name="Best Paw Nutrition",
        user_id="334430",
        reasons=(TerminalReason.CLAIM_TOO_OLD,),
        findings=("The claim was filed 73 days after delivery.",),
        gates=ALL_FOUR_GATES,
        context=make_context(),
        drafted_email=DraftedEmail(to="sakukreja@shipbob.com", subject="Your claim", body="..."),
        requires_rep_clarification=False,
    )


def make_result(**overrides: Any) -> PreflightResult:
    fields: dict[str, Any] = {
        "case_id": "CASE-1001",
        "verdict": Verdict.PROCEED,
        "gates": ALL_FOUR_GATES,
        "record": make_record(),
        "context": make_context(),
        "evaluated_at": FILED_AT,
    }
    fields.update(overrides)
    return PreflightResult(**fields)


@pytest.mark.parametrize(
    ("case_value", "shipment_value", "expected"),
    [
        (DELIVERED, DELIVERED, False),
        (DELIVERED, DELIVERED_A_DAY_LATER, True),
        (DELIVERED, None, False),
        (None, DELIVERED, False),
    ],
)
def test_the_two_delivery_dates_only_disagree_when_both_are_there(
    case_value: datetime | None,
    shipment_value: datetime | None,
    expected: bool,
) -> None:
    source: Literal["case", "shipment"] = "case" if case_value is not None else "shipment"
    delivery = DeliveryDate(
        value=case_value or shipment_value,
        source=source,
        case_value=case_value,
        shipment_value=shipment_value,
    )

    assert delivery.sources_disagree is expected


def test_no_delivery_date_anywhere_is_a_state_of_its_own() -> None:
    delivery = DeliveryDate(value=None, source="none", case_value=None, shipment_value=None)

    assert delivery.value is None
    assert delivery.sources_disagree is False


def test_a_check_records_the_values_it_looked_at() -> None:
    gate = make_gate(GateName.AGE)

    assert gate.observed["days_since_delivery"] == "8"
    assert gate.reason is None


def test_the_order_value_a_rep_sees_keeps_its_cents() -> None:
    assert make_context().model_dump(mode="json")["order_value_usd"] == "90.00"


def test_an_unreadable_order_leaves_the_value_unknown_rather_than_nought() -> None:
    context = make_context(order_value_usd=None, is_high_value=False)

    assert context.order_value_usd is None
    assert make_record().order is None


def test_a_claim_that_may_proceed_carries_all_four_checks_and_no_reasons() -> None:
    result = make_result()

    assert result.verdict is Verdict.PROCEED
    assert len(result.gates) == 4
    assert result.terminal_reasons == ()
    assert result.report is None


def test_a_stopped_claim_carries_its_reasons_and_the_rep_s_report() -> None:
    result = make_result(
        verdict=Verdict.TERMINAL,
        terminal_reasons=(TerminalReason.CLAIM_TOO_OLD,),
        report=make_report(),
    )

    assert result.report is not None
    assert result.report.requires_rep_approval is True


def test_a_stopped_claim_with_no_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one reason"):
        make_result(verdict=Verdict.TERMINAL, report=make_report())


def test_a_stopped_claim_with_no_report_is_refused() -> None:
    with pytest.raises(ValidationError, match="report for the rep"):
        make_result(verdict=Verdict.TERMINAL, terminal_reasons=(TerminalReason.CLAIM_TOO_OLD,))


def test_a_claim_allowed_through_while_still_carrying_reasons_to_stop_is_refused() -> None:
    with pytest.raises(ValidationError, match="must not carry terminal reasons"):
        make_result(terminal_reasons=(TerminalReason.SHIPMENT_INSURED,))


def test_a_claim_allowed_through_while_carrying_a_stop_report_is_refused() -> None:
    with pytest.raises(ValidationError, match="must not carry a terminal report"):
        make_result(report=make_report())


def test_an_insured_claim_that_is_not_marked_for_rep_clarification_is_refused() -> None:
    with pytest.raises(ValidationError, match="requires_rep_clarification"):
        TerminalReport(
            case_id="CASE-9001",
            account_name="Constructed Insured Merchant",
            user_id="990000001",
            reasons=(TerminalReason.SHIPMENT_INSURED,),
            findings=("This shipment was insured.",),
            gates=ALL_FOUR_GATES,
            context=make_context(),
            drafted_email=None,
            requires_rep_clarification=False,
        )


def test_a_claim_with_nothing_to_tell_the_merchant_must_not_carry_an_email() -> None:
    with pytest.raises(ValidationError, match="must not carry an email"):
        TerminalReport(
            case_id="CASE-9001",
            account_name="Constructed Insured Merchant",
            user_id="990000001",
            reasons=(TerminalReason.SHIPMENT_INSURED,),
            findings=("This shipment was insured.",),
            gates=ALL_FOUR_GATES,
            context=make_context(),
            drafted_email=DraftedEmail(to="someone@example.com", subject="s", body="b"),
            requires_rep_clarification=True,
        )


def test_a_reason_the_merchant_could_be_told_needs_an_email() -> None:
    with pytest.raises(ValidationError, match="needs an email"):
        TerminalReport(
            case_id="CASE-1004",
            account_name="Catalyze-X",
            user_id="374167",
            reasons=(TerminalReason.CLAIM_TOO_OLD,),
            findings=("The claim was filed 73 days after delivery.",),
            gates=ALL_FOUR_GATES,
            context=make_context(),
            drafted_email=None,
            requires_rep_clarification=False,
        )
