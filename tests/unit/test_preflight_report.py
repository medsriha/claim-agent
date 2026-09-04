"""The write-up a rep gets when a claim cannot be processed at all (FR-0.4).

The email inside the write-up has its own tests next door; these are about the write-up
around it — what it summarises, what it keeps, and what it deliberately never says.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from tests.fixtures.shipbob import CASE_1004, without

from claim_agent.domain.models import Case, GateName, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.models import ClaimContext, GateResult, TerminalReport
from claim_agent.preflight.report import build_terminal_report

# What the age check recorded on CASE-1004: delivered 26 December 2025, opened 9 March
# 2026, 73 days apart. Both dates and the day count are quoted in REQUIREMENTS.md.
AGE_OBSERVED = {
    "case_delivered_date": "2025-12-26T12:13:36+00:00",
    "shipment_delivered_date": "2025-12-26T12:13:36+00:00",
    "delivered_date_used": "2025-12-26T12:13:36+00:00",
    "delivered_date_taken_from": "the claim record",
    "case_created_date": "2026-03-09T18:51:42+00:00",
    "days_since_delivery": "73",
    "age_limit_days": "60",
    "limit_day_still_counts": "yes",
}

AGE_FAILED = GateResult(
    gate=GateName.AGE,
    passed=False,
    reason=TerminalReason.CLAIM_TOO_OLD,
    explanation="The claim was opened 73 days after delivery, past the 60 day limit.",
    observed=AGE_OBSERVED,
)

KEY_INFORMATION_FAILED = GateResult(
    gate=GateName.KEY_INFORMATION,
    passed=False,
    reason=TerminalReason.MISSING_KEY_INFORMATION,
    explanation="This claim is missing a description of what happened.",
    observed={"missing": "a description of what happened"},
)

CLAIM_TYPE_PASSED = GateResult(
    gate=GateName.CLAIM_TYPE,
    passed=True,
    explanation="The case is a damaged-in-transit claim.",
    observed={"sub_category": "Claim | Damaged in Transit"},
)

INSURANCE_PASSED = GateResult(
    gate=GateName.INSURANCE,
    passed=True,
    explanation="The shipment was not insured.",
    observed={"is_insured": "false"},
)

INSURANCE_FAILED = GateResult(
    gate=GateName.INSURANCE,
    passed=False,
    reason=TerminalReason.SHIPMENT_INSURED,
    explanation=(
        "This shipment was insured, and insured shipments are claimed on their insurance "
        "through a different process."
    ),
    observed={"is_insured": "true"},
)

AGE_PASSED = GateResult(
    gate=GateName.AGE,
    passed=True,
    explanation="The claim was opened 2 days after delivery, within the 60 day limit.",
    observed={"days_since_delivery": "2", "age_limit_days": "60"},
)

KEY_INFORMATION_PASSED = GateResult(
    gate=GateName.KEY_INFORMATION,
    passed=True,
    explanation="The claim names a parcel and an order, and the merchant described what happened.",
    observed={"missing": ""},
)

ALL_FOUR_GATES = (AGE_FAILED, CLAIM_TYPE_PASSED, KEY_INFORMATION_FAILED, INSURANCE_PASSED)

# An insured claim with nothing else wrong with it: the only thing stopping it is the
# one thing a merchant is never written to about.
ONLY_INSURED_GATES = (AGE_PASSED, CLAIM_TYPE_PASSED, KEY_INFORMATION_PASSED, INSURANCE_FAILED)

# Insured and too old at once, which is the case where a representative has a choice.
INSURED_AND_TOO_OLD_GATES = (
    AGE_FAILED,
    CLAIM_TYPE_PASSED,
    KEY_INFORMATION_PASSED,
    INSURANCE_FAILED,
)


def make_context(**overrides: Any) -> ClaimContext:
    """Build the facts worked out about CASE-1004 before the checks ran."""
    fields: dict[str, Any] = {
        "order_value_usd": Decimal("24.99"),
        "is_high_value": False,
        "days_since_delivery": 73,
        "delivered_date": "2025-12-26T12:13:36+00:00",
    }
    fields.update(overrides)
    return ClaimContext(**fields)


def build(
    *,
    case: Case | None = None,
    reasons: tuple[TerminalReason, ...] = (TerminalReason.CLAIM_TOO_OLD,),
    gates: tuple[GateResult, ...] = ALL_FOUR_GATES,
    context: ClaimContext | None = None,
) -> TerminalReport:
    """Write up CASE-1004 as a stopped claim, varying only what a test cares about."""
    return build_terminal_report(
        case if case is not None else Case.model_validate(CASE_1004),
        reasons,
        gates,
        context if context is not None else make_context(),
        Policy(),
    )


def test_a_stopped_claim_produces_a_write_up_carrying_a_drafted_email() -> None:
    """FR-0.4: a claim that cannot be processed still reaches a rep as something to approve."""
    report = build()

    assert report.case_id == "CASE-1004"
    assert report.drafted_email is not None
    assert report.drafted_email.body
    assert report.requires_rep_approval is True


def test_the_write_up_says_who_the_claim_is_from() -> None:
    """FR-0.4: a rep approving a closure needs to see whose claim they are closing."""
    report = build()

    assert report.account_name == "Catalyze-X"
    assert report.user_id == "374167"


def test_a_case_naming_no_merchant_still_produces_a_write_up() -> None:
    """FR-0.4: the merchant name is display text and can be absent; the claim still closes."""
    report = build(case=Case.model_validate(without(CASE_1004, "account_name", "user_id")))

    assert report.account_name is None
    assert report.user_id is None
    assert report.drafted_email is not None
    assert report.drafted_email.body


def test_the_summary_holds_one_sentence_for_each_check_that_failed() -> None:
    """NFR-3: a rep reads why the claim stopped without having to decode the raw values."""
    report = build(reasons=(TerminalReason.CLAIM_TOO_OLD, TerminalReason.MISSING_KEY_INFORMATION))

    assert report.findings == (AGE_FAILED.explanation, KEY_INFORMATION_FAILED.explanation)


def test_the_write_up_keeps_the_checks_that_passed_as_well() -> None:
    """NFR-3: a rep can see the insurance check ran and passed, rather than infer it."""
    report = build()

    assert len(report.gates) == 4
    assert [gate.gate for gate in report.gates] == [
        GateName.AGE,
        GateName.CLAIM_TYPE,
        GateName.KEY_INFORMATION,
        GateName.INSURANCE,
    ]
    assert [gate.passed for gate in report.gates] == [False, True, False, True]


def test_the_reasons_are_kept_in_the_order_they_arrived_in() -> None:
    """FR-0.4: the report must not reorder them — the first names the email's subject."""
    reasons = (TerminalReason.CLAIM_TOO_OLD, TerminalReason.MISSING_KEY_INFORMATION)

    report = build(reasons=reasons)

    assert report.reasons == reasons
    assert report.drafted_email is not None
    assert "opened too long after delivery" in report.drafted_email.subject


def test_the_facts_gathered_up_front_travel_with_the_write_up() -> None:
    """FR-0.5: the work already done is not thrown away because the claim stopped."""
    report = build()

    assert report.context.days_since_delivery == 73
    assert report.context.order_value_usd == Decimal("24.99")


def test_the_write_up_names_no_amount_of_money() -> None:
    """FR-0.4: the pre-flight screen recommends nothing, so it has no figure to give.

    The value of the order still travels with the write-up as a fact a rep may want. What
    must not appear is money in the words — a sum in a finding or in the merchant's email
    would read as an offer nobody has made.
    """
    report = build()
    assert report.drafted_email is not None
    written = " ".join([*report.findings, report.drafted_email.subject, report.drafted_email.body])

    assert "$" not in written
    assert "24.99" not in written


def test_a_stopped_claim_with_no_reason_at_all_is_refused() -> None:
    """FR-0.4: a claim stopped for nothing anyone can name would reach a rep as a blank."""
    with pytest.raises(ValueError, match="at least one reason"):
        build(reasons=())


def test_an_insured_claim_is_escalated_and_carries_no_merchant_email() -> None:
    """FR-0.2: an insured claim is routed out, not answered, so there is nothing to send.

    Insured shipments are claimed on their insurance, through a process that is not
    ours. Nobody writes to the merchant about that, so the write-up hands a
    representative an escalation instead of an email.
    """
    report = build(reasons=(TerminalReason.SHIPMENT_INSURED,), gates=ONLY_INSURED_GATES)

    assert report.requires_escalation is True
    assert report.drafted_email is None
    assert report.findings == (INSURANCE_FAILED.explanation,)


def test_a_claim_both_insured_and_too_old_carries_the_email_and_the_escalation() -> None:
    """FR-0.2, FR-0.4: the representative chooses, and is given both things to choose from.

    Being too old is something a merchant can be told. Being insured is not. A claim
    that is both therefore produces an email about its age *and* an escalation, and
    nothing here decides which of the two a representative acts on.
    """
    report = build(
        reasons=(TerminalReason.SHIPMENT_INSURED, TerminalReason.CLAIM_TOO_OLD),
        gates=INSURED_AND_TOO_OLD_GATES,
    )

    assert report.requires_escalation is True
    assert report.drafted_email is not None
    assert "73 days" in report.drafted_email.body


def test_the_merchant_email_never_mentions_the_insurance() -> None:
    """FR-0.2: whichever else fails, the insurance is not the merchant's business here.

    The subject line is the interesting half. It is taken from the first reason a
    merchant can be told about, so on a claim led by being insured it has to skip past
    that one rather than announce it.
    """
    report = build(
        reasons=(TerminalReason.SHIPMENT_INSURED, TerminalReason.CLAIM_TOO_OLD),
        gates=INSURED_AND_TOO_OLD_GATES,
    )

    assert report.drafted_email is not None
    assert "insur" not in report.drafted_email.subject.lower()
    assert "insur" not in report.drafted_email.body.lower()


def test_a_claim_stopped_by_anything_else_needs_no_escalation() -> None:
    """FR-0.4: an ordinary stopped claim is closed with an explanation, and that is all."""
    report = build()

    assert report.requires_escalation is False
    assert report.drafted_email is not None


def test_the_insurance_finding_still_reaches_the_representative() -> None:
    """NFR-3: the reason it was routed out has to be readable, or the escalation is a shrug.

    The sentence a representative reads is the insurance check's own. It is the only
    place that reason is written down now that no email carries it.
    """
    report = build(reasons=(TerminalReason.SHIPMENT_INSURED,), gates=ONLY_INSURED_GATES)

    assert "insured" in report.findings[0]
    assert report.reasons[0] is TerminalReason.SHIPMENT_INSURED
