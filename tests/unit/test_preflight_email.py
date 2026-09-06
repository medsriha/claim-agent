from __future__ import annotations

import locale
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from tests.fixtures.shipbob import CASE_1004, without

from claim_agent.domain.models import Case, DraftedEmail, GateName, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.email import draft_terminal_email
from claim_agent.preflight.models import ClaimContext, GateResult

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


def age_gate(observed: dict[str, str] | None = None) -> GateResult:
    return GateResult(
        gate=GateName.AGE,
        passed=False,
        reason=TerminalReason.CLAIM_TOO_OLD,
        explanation="The claim was opened 73 days after delivery, past the 60 day limit.",
        observed=dict(AGE_OBSERVED) if observed is None else observed,
    )


def key_information_gate(
    missing: str | None = "the parcel's id, a description of what happened",
) -> GateResult:
    observed = {} if missing is None else {"missing": missing}
    return GateResult(
        gate=GateName.KEY_INFORMATION,
        passed=False,
        reason=TerminalReason.MISSING_KEY_INFORMATION,
        explanation="This claim is missing the parcel's id and a description of what happened.",
        observed=observed,
    )


def claim_type_gate() -> GateResult:
    return GateResult(
        gate=GateName.CLAIM_TYPE,
        passed=False,
        reason=TerminalReason.WRONG_CLAIM_TYPE,
        explanation='The case is recorded as "Claim | Lost in Transit", not a damage claim.',
        observed={"sub_category": "Claim | Lost in Transit"},
    )


def insurance_gate(*, passed: bool = True) -> GateResult:
    return GateResult(
        gate=GateName.INSURANCE,
        passed=passed,
        reason=None if passed else TerminalReason.SHIPMENT_INSURED,
        explanation=("The shipment was not insured." if passed else "The shipment was insured."),
        observed={"is_insured": "false" if passed else "true"},
    )


def all_gates(**overrides: GateResult) -> tuple[GateResult, ...]:
    gates = {
        "age": age_gate(),
        "claim_type": claim_type_gate(),
        "key_information": key_information_gate(),
        "insurance": insurance_gate(),
    }
    gates.update(overrides)
    return tuple(gates.values())


def make_context(**overrides: Any) -> ClaimContext:
    fields: dict[str, Any] = {
        "order_value_usd": Decimal("24.99"),
        "is_high_value": False,
        "days_since_delivery": 73,
        "delivered_date": "2025-12-26T12:13:36+00:00",
    }
    fields.update(overrides)
    return ClaimContext(**fields)


def draft(
    *,
    case: Case | None = None,
    reasons: tuple[TerminalReason, ...] = (TerminalReason.CLAIM_TOO_OLD,),
    gates: tuple[GateResult, ...] | None = None,
    context: ClaimContext | None = None,
    policy: Policy | None = None,
) -> DraftedEmail:
    return draft_terminal_email(
        case if case is not None else Case.model_validate(CASE_1004),
        reasons,
        gates if gates is not None else all_gates(),
        context if context is not None else make_context(),
        policy if policy is not None else Policy(),
    )


@pytest.fixture
def french_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LC_TIME", "fr_FR.UTF-8")
    original = locale.setlocale(locale.LC_TIME)
    for name in ("fr_FR.UTF-8", "fr_FR.utf8", "fr_FR"):
        try:
            locale.setlocale(locale.LC_TIME, name)
        except locale.Error:
            continue
        break
    try:
        yield
    finally:
        locale.setlocale(locale.LC_TIME, original)


def test_a_stopped_claim_still_gets_an_email_written_for_it() -> None:
    email = draft()

    assert email.subject
    assert email.body


def test_the_email_is_addressed_to_the_merchant_on_the_case() -> None:
    email = draft()

    assert email.to == "sakukreja+6@shipbob.com"


def test_the_email_names_every_reason_the_claim_was_declined() -> None:
    email = draft(
        reasons=(
            TerminalReason.CLAIM_TOO_OLD,
            TerminalReason.WRONG_CLAIM_TYPE,
            TerminalReason.MISSING_KEY_INFORMATION,
        ),
    )

    assert "73 days" in email.body
    assert "damaged in transit" in email.body
    assert "the parcel's id" in email.body


def test_being_insured_is_never_explained_to_a_merchant() -> None:
    with pytest.raises(ValueError, match="never explained to the merchant"):
        draft(
            reasons=(TerminalReason.SHIPMENT_INSURED,),
            gates=all_gates(insurance=insurance_gate(passed=False)),
        )


def test_the_reasons_appear_in_the_order_the_email_was_given_them() -> None:
    email = draft(reasons=(TerminalReason.WRONG_CLAIM_TYPE, TerminalReason.CLAIM_TOO_OLD))

    assert email.body.index("damaged in transit") < email.body.index("73 days")


@pytest.mark.parametrize(
    ("leading_reason", "expected_in_subject"),
    [
        (TerminalReason.CLAIM_TOO_OLD, "too long after delivery"),
        (TerminalReason.WRONG_CLAIM_TYPE, "not a damage-in-transit claim"),
        (TerminalReason.MISSING_KEY_INFORMATION, "details are missing"),
    ],
)
def test_the_subject_line_comes_from_the_leading_reason(
    leading_reason: TerminalReason, expected_in_subject: str
) -> None:
    email = draft(
        reasons=(leading_reason, TerminalReason.MISSING_KEY_INFORMATION),
        gates=all_gates(insurance=insurance_gate(passed=False)),
    )

    assert expected_in_subject in email.subject
    assert "CASE-1004" in email.subject


@pytest.mark.parametrize(
    ("reason", "expected_fragments"),
    [
        (
            TerminalReason.CLAIM_TOO_OLD,
            ("26 December 2025", "9 March 2026", "73 days", "60 days"),
        ),
        (TerminalReason.WRONG_CLAIM_TYPE, ("damaged in transit", "Claim | Lost in Transit")),
        (
            TerminalReason.MISSING_KEY_INFORMATION,
            ("the parcel's id", "a description of what happened"),
        ),
    ],
)
def test_each_reason_is_explained_with_the_claim_s_own_facts(
    reason: TerminalReason, expected_fragments: tuple[str, ...]
) -> None:
    case = Case.model_validate({**CASE_1004, "sub_category": "Claim | Lost in Transit"})
    email = draft(
        case=case,
        reasons=(reason,),
        gates=all_gates(insurance=insurance_gate(passed=False)),
    )

    for fragment in expected_fragments:
        assert fragment in email.body


def test_the_missing_details_are_named_one_by_one() -> None:
    email = draft(
        reasons=(TerminalReason.MISSING_KEY_INFORMATION,),
        gates=all_gates(
            key_information=key_information_gate(
                missing="the parcel's id, the order's id, a description of what happened"
            )
        ),
    )

    assert "the parcel's id, the order's id and a description of what happened" in email.body


def test_the_body_carries_no_draft_marker_although_the_email_is_one() -> None:
    email = draft()

    assert "draft" not in email.body.lower()
    assert "draft" not in email.subject.lower()
    assert email.is_draft is True


def test_a_case_with_no_contact_address_still_gets_its_reasons_written() -> None:
    case = Case.model_validate(without(CASE_1004, "contact_email"))

    email = draft(case=case)

    assert email.to is None
    assert "73 days" in email.body


def test_the_greeting_uses_the_merchant_s_name() -> None:
    assert draft().body.startswith("Hi Catalyze-X,")


def test_the_greeting_falls_back_when_the_case_names_no_merchant() -> None:
    case = Case.model_validate(without(CASE_1004, "account_name"))

    assert draft(case=case).body.startswith("Hi there,")


@pytest.mark.usefixtures("french_host")
def test_the_month_name_does_not_change_with_the_host_s_language() -> None:
    email = draft()

    assert "26 December 2025" in email.body
    assert "décembre" not in email.body


def test_the_same_claim_produces_the_same_email_twice() -> None:
    first = draft()
    second = draft()

    assert first.subject == second.subject
    assert first.body == second.body


def test_the_age_limit_quoted_is_the_one_the_policy_holds() -> None:
    email = draft(policy=Policy(max_claim_age_days=30))

    assert "within 30 days of delivery" in email.body
    assert "60 days" not in email.body


def test_a_one_day_limit_is_not_written_as_one_days() -> None:
    email = draft(policy=Policy(max_claim_age_days=1))

    assert "within 1 day of delivery" in email.body


def test_an_age_check_that_recorded_nothing_still_gets_a_sensible_sentence() -> None:
    email = draft(
        gates=all_gates(age=age_gate(observed={})),
        context=make_context(days_since_delivery=None, delivered_date=None),
    )

    assert "within 60 days of delivery" in email.body
    assert "None" not in email.body


def test_a_value_the_check_could_not_fill_in_falls_back_to_the_facts_gathered_up_front() -> None:
    email = draft(
        gates=all_gates(
            age=age_gate(
                observed={"delivered_date_used": "not recorded", "days_since_delivery": "not known"}
            )
        )
    )

    assert "26 December 2025" in email.body
    assert "73 days" in email.body


def test_an_age_check_missing_from_the_list_altogether_still_produces_an_email() -> None:
    email = draft(
        gates=(insurance_gate(),),
        context=make_context(days_since_delivery=None, delivered_date=None),
    )

    assert "within 60 days of delivery" in email.body


def test_a_missing_information_check_that_named_nothing_still_says_what_is_needed() -> None:
    email = draft(
        reasons=(TerminalReason.MISSING_KEY_INFORMATION,),
        gates=all_gates(key_information=key_information_gate(missing=None)),
    )

    assert "the shipment, the order it came from, and a description" in email.body


def test_a_case_with_no_recorded_claim_type_still_explains_the_routing() -> None:
    case = Case.model_validate(without(CASE_1004, "sub_category"))

    email = draft(case=case, reasons=(TerminalReason.WRONG_CLAIM_TYPE,))

    assert "damaged in transit" in email.body
    assert "passing it to the team" in email.body


def test_an_email_with_no_reason_at_all_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one reason"):
        draft(reasons=())
