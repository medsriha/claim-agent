from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from claim_agent.admin.models import (
    PolicyUpdate,
    PolicyValueChoice,
    PolicyValueKind,
    PolicyValueWritten,
    PolicyValueYesNo,
)
from claim_agent.admin.panel import describe_policy, revise_policy
from claim_agent.errors import InvalidRequestError
from claim_agent.live_policy import LivePolicy
from claim_agent.policy import KNOWN_CLAIM_SUB_CATEGORIES, Policy

A_MOMENT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def in_force(policy: Policy | None = None) -> LivePolicy:
    return LivePolicy(policy if policy is not None else Policy())


def test_every_policy_value_is_on_the_panel_exactly_once() -> None:
    view = describe_policy(in_force())

    names = [value.name for value in view.values]
    assert names == [
        "reimbursement_cap_usd",
        "max_claim_age_days",
        "age_limit_inclusive",
        "high_value_order_usd",
        "high_value_inclusive",
        "damaged_in_transit_sub_category",
    ]


def test_the_values_left_off_the_panel_are_still_part_of_the_policy() -> None:
    view = describe_policy(in_force())

    left_off = set(Policy.model_fields) - {value.name for value in view.values}
    assert left_off == {
        "min_description_length",
        "max_agent_steps",
        "max_tool_calls_per_step",
        "max_image_analyses_per_run",
        "precedent_results_per_product",
        "min_precedent_similarity",
        "usd_conversion_rates",
        "conversion_rates_as_of",
        "assume_usd_when_currency_unknown",
        "default_date_region",
        "price_divergence_fraction",
        "document_total_tolerance",
        "unanswerable_case_statuses",
        "internal_email_domain",
        "min_order_reference_confidence",
        "min_item_match_confidence",
    }
    assert Policy().max_agent_steps == 12


def test_a_value_the_panel_does_not_show_cannot_be_changed_through_it() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_agent_steps": "3"}))

    assert "cannot be changed from the admin panel" in refused.value.message
    assert refused.value.details["values"][0]["name"] == "max_agent_steps"


def test_a_value_carries_the_explanation_written_beside_it_in_the_policy_file() -> None:
    view = describe_policy(in_force())

    age_limit = next(value for value in view.values if value.name == "max_claim_age_days")
    assert age_limit.description == Policy.model_fields["max_claim_age_days"].description


def test_money_is_described_as_text_never_as_a_number() -> None:
    view = describe_policy(in_force(Policy(reimbursement_cap_usd=Decimal("100.00"))))

    cap = next(value for value in view.values if value.name == "reimbursement_cap_usd")
    assert isinstance(cap, PolicyValueWritten)
    assert cap.kind is PolicyValueKind.MONEY
    assert cap.value == "100.00"


def test_a_yes_or_no_is_described_as_a_yes_or_no() -> None:
    view = describe_policy(in_force(Policy(age_limit_inclusive=False)))

    inclusive = next(value for value in view.values if value.name == "age_limit_inclusive")
    assert isinstance(inclusive, PolicyValueYesNo)
    assert inclusive.kind is PolicyValueKind.BOOLEAN
    assert inclusive.value is False


def test_the_claim_type_is_described_as_a_choice_not_a_text_box() -> None:
    view = describe_policy(in_force(Policy()))

    claim_type = next(
        value for value in view.values if value.name == "damaged_in_transit_sub_category"
    )
    assert isinstance(claim_type, PolicyValueChoice)
    assert claim_type.kind is PolicyValueKind.CHOICE
    assert claim_type.value == "Claim | Damaged in Transit"
    assert claim_type.options == KNOWN_CLAIM_SUB_CATEGORIES


def test_a_claim_type_nobody_listed_is_still_offered_so_it_cannot_be_lost() -> None:
    unlisted = "Claim | Something We Have Never Seen"

    view = describe_policy(in_force(Policy(damaged_in_transit_sub_category=unlisted)))

    claim_type = next(
        value for value in view.values if value.name == "damaged_in_transit_sub_category"
    )
    assert isinstance(claim_type, PolicyValueChoice)
    assert claim_type.value == unlisted
    assert unlisted in claim_type.options

    assert claim_type.options[: len(KNOWN_CLAIM_SUB_CATEGORIES)] == KNOWN_CLAIM_SUB_CATEGORIES


def test_only_a_value_that_names_its_choices_becomes_a_list() -> None:
    view = describe_policy(in_force(Policy()))

    chosen = [value.name for value in view.values if isinstance(value, PolicyValueChoice)]
    assert chosen == ["damaged_in_transit_sub_category"]

    for value in view.values:
        if isinstance(value, PolicyValueChoice):
            assert value.options


def test_a_changed_value_is_marked_and_still_shows_what_it_started_as() -> None:
    live = in_force(Policy(max_claim_age_days=60))
    live.replace(Policy(max_claim_age_days=5), changed_at=A_MOMENT)

    view = describe_policy(live)

    age_limit = next(value for value in view.values if value.name == "max_claim_age_days")
    assert isinstance(age_limit, PolicyValueWritten)
    assert age_limit.changed is True
    assert age_limit.value == "5"
    assert age_limit.startup_value == "60"
    assert view.changed_at == A_MOMENT
    assert view.matches_startup is False


def test_an_untouched_policy_says_it_matches_what_the_service_started_with() -> None:
    view = describe_policy(in_force())

    assert view.matches_startup is True
    assert view.changed_at is None
    assert all(value.changed is False for value in view.values)


def test_a_submitted_value_is_laid_over_the_one_in_force() -> None:
    current = Policy(max_claim_age_days=60, reimbursement_cap_usd=Decimal("100.00"))

    revised = revise_policy(current, PolicyUpdate(values={"max_claim_age_days": "5"}))

    assert revised.max_claim_age_days == 5
    assert revised.reimbursement_cap_usd == Decimal("100.00")


def test_money_typed_as_text_keeps_every_cent() -> None:
    revised = revise_policy(Policy(), PolicyUpdate(values={"reimbursement_cap_usd": "99.99"}))

    assert revised.reimbursement_cap_usd == Decimal("99.99")


def test_a_name_that_is_not_a_policy_value_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_claim_age_dayz": "5"}))

    assert "max_claim_age_dayz" in refused.value.message
    assert refused.value.details["values"] == [
        {"name": "max_claim_age_dayz", "message": "The claim policy has no value with this name."}
    ]


def test_two_unknown_names_are_both_named_in_the_complaint() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"nonsense": "1", "more_nonsense": "2"}))

    assert "nonsense, more_nonsense" in refused.value.message
    assert len(refused.value.details["values"]) == 2


def test_a_value_outside_its_allowed_range_is_refused_with_a_reason() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_agent_steps": "0"}))

    assert refused.value.status_code == 400
    assert "max_agent_steps" in refused.value.message
    problems = refused.value.details["values"]
    assert [problem["name"] for problem in problems] == ["max_agent_steps"]
    assert problems[0]["message"] != ""


def test_every_refused_value_gets_its_own_complaint() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(
            Policy(),
            PolicyUpdate(values={"max_agent_steps": "0", "max_image_analyses_per_run": "0"}),
        )

    named = {problem["name"] for problem in refused.value.details["values"]}
    assert named == {"max_agent_steps", "max_image_analyses_per_run"}


def test_words_can_be_changed_too() -> None:
    revised = revise_policy(
        Policy(), PolicyUpdate(values={"damaged_in_transit_sub_category": "Claim | Damaged"})
    )

    assert revised.damaged_in_transit_sub_category == "Claim | Damaged"


def test_submitting_nothing_gives_back_the_policy_unchanged() -> None:
    current = Policy(max_claim_age_days=42)

    revised = revise_policy(current, PolicyUpdate(values={}))

    assert revised == current
