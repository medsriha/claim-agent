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
    """Hold a policy as the one in force, so each test starts from a known place."""
    return LivePolicy(policy if policy is not None else Policy())


def test_every_policy_value_is_on_the_panel_exactly_once() -> None:
    """FR-0.7, NFR-7: the panel is drawn from the policy file, so nothing is missed.

    This is the test that keeps the two in step. Add a threshold to the policy file
    and it appears on the screen; if it cannot be described, this fails rather than
    the value silently becoming uneditable.

    The list is written out rather than worked out, so that a value appearing on the
    panel — or quietly vanishing from it — has to be an edit somebody made here on
    purpose.
    """
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
    """FR-0.7: off the panel is not gone — they are read, and set from the environment.

    They fall into three groups. Seven belong to the AI investigation, which is being
    built but is not yet reachable, so changing one from a screen would do nothing
    anybody could see. One is the shortest acceptable description, which the checks do
    read; it is off the panel because it is not a knob for demonstrating anything. The
    last ten are the reading tools' values, and they are off the panel for a plainer
    reason: several are a table or a list rather than a single figure, and the panel
    draws one control per value. A conversion rate table needs a screen of its own.
    """
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
    """FR-0.7: leaving a value off the screen but honouring it here would be cosmetic.

    Anyone sending the request by hand could still change it, which is not what being
    off the panel is meant to mean.
    """
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_agent_steps": "3"}))

    assert "cannot be changed from the admin panel" in refused.value.message
    assert refused.value.details["values"][0]["name"] == "max_agent_steps"


def test_a_value_carries_the_explanation_written_beside_it_in_the_policy_file() -> None:
    """FR-0.7: the words on screen are the service's own, including "PROVISIONAL"."""
    view = describe_policy(in_force())

    age_limit = next(value for value in view.values if value.name == "max_claim_age_days")
    assert age_limit.description == Policy.model_fields["max_claim_age_days"].description


def test_money_is_described_as_text_never_as_a_number() -> None:
    """FR-1.21, NFR-2: an amount must not pass through a browser number.

    A cap sent as a number can come back as 100.00000000000001. Sent as text it
    cannot, and the panel has nothing it could do arithmetic on.
    """
    view = describe_policy(in_force(Policy(reimbursement_cap_usd=Decimal("100.00"))))

    cap = next(value for value in view.values if value.name == "reimbursement_cap_usd")
    assert isinstance(cap, PolicyValueWritten)
    assert cap.kind is PolicyValueKind.MONEY
    assert cap.value == "100.00"


def test_a_yes_or_no_is_described_as_a_yes_or_no() -> None:
    """FR-0.7: a toggle is a toggle, and not the word "True" in a text box.

    In Python a yes-or-no is a kind of whole number, which is exactly the trap this
    guards: describing it by its type has to notice the toggle first.
    """
    view = describe_policy(in_force(Policy(age_limit_inclusive=False)))

    inclusive = next(value for value in view.values if value.name == "age_limit_inclusive")
    assert isinstance(inclusive, PolicyValueYesNo)
    assert inclusive.kind is PolicyValueKind.BOOLEAN
    assert inclusive.value is False


def test_the_claim_type_is_described_as_a_choice_not_a_text_box() -> None:
    """FR-0.2, FR-0.7: the claim-type prefix is picked rather than typed.

    A typo in this value turns every claim away at the claim-type check, which is the
    reason it is offered as a list rather than a box.
    """
    view = describe_policy(in_force(Policy()))

    claim_type = next(
        value for value in view.values if value.name == "damaged_in_transit_sub_category"
    )
    assert isinstance(claim_type, PolicyValueChoice)
    assert claim_type.kind is PolicyValueKind.CHOICE
    assert claim_type.value == "Claim | Damaged in Transit"
    assert claim_type.options == KNOWN_CLAIM_SUB_CATEGORIES


def test_a_claim_type_nobody_listed_is_still_offered_so_it_cannot_be_lost() -> None:
    """FR-0.2: the list is what the panel suggests, not what the service accepts.

    Only one claim type is recorded in REQUIREMENTS.md and ShipBob certainly uses others,
    so the list is deliberately short rather than a guess at the rest. A claim type set
    from the environment must therefore still appear in the control — otherwise saving the
    form would quietly replace a perfectly valid setting with the only listed choice.
    """
    unlisted = "Claim | Something We Have Never Seen"

    view = describe_policy(in_force(Policy(damaged_in_transit_sub_category=unlisted)))

    claim_type = next(
        value for value in view.values if value.name == "damaged_in_transit_sub_category"
    )
    assert isinstance(claim_type, PolicyValueChoice)
    assert claim_type.value == unlisted
    assert unlisted in claim_type.options
    # The listed choices are still there, and still in the order the policy gives them.
    assert claim_type.options[: len(KNOWN_CLAIM_SUB_CATEGORIES)] == KNOWN_CLAIM_SUB_CATEGORIES


def test_only_a_value_that_names_its_choices_becomes_a_list() -> None:
    """FR-0.7: the control comes from what the policy declares, and nothing else.

    A value says it should be picked from a list by naming the choices alongside its
    type. That is the same channel other notes about a value travel on, so this guards
    against a value carrying some *other* note being mistaken for one with choices —
    which would put an empty dropdown where a box belongs, and make the value
    unchangeable.
    """
    view = describe_policy(in_force(Policy()))

    chosen = [value.name for value in view.values if isinstance(value, PolicyValueChoice)]
    assert chosen == ["damaged_in_transit_sub_category"]
    # And nothing offered as a list may offer an empty one, which nobody could pick from.
    for value in view.values:
        if isinstance(value, PolicyValueChoice):
            assert value.options


def test_a_changed_value_is_marked_and_still_shows_what_it_started_as() -> None:
    """FR-0.7: someone has to be able to see what they have changed, and from what."""
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
    """FR-0.7: with nothing changed there is nothing to reset."""
    view = describe_policy(in_force())

    assert view.matches_startup is True
    assert view.changed_at is None
    assert all(value.changed is False for value in view.values)


def test_a_submitted_value_is_laid_over_the_one_in_force() -> None:
    """FR-0.7: one value can be changed without restating the rest of the policy."""
    current = Policy(max_claim_age_days=60, reimbursement_cap_usd=Decimal("100.00"))

    revised = revise_policy(current, PolicyUpdate(values={"max_claim_age_days": "5"}))

    assert revised.max_claim_age_days == 5
    assert revised.reimbursement_cap_usd == Decimal("100.00")


def test_money_typed_as_text_keeps_every_cent() -> None:
    """FR-1.21, NFR-2: the exact figure typed is the exact figure judged against."""
    revised = revise_policy(Policy(), PolicyUpdate(values={"reimbursement_cap_usd": "99.99"}))

    assert revised.reimbursement_cap_usd == Decimal("99.99")


def test_a_name_that_is_not_a_policy_value_is_refused() -> None:
    """FR-0.7: a misspelled name must not be accepted and then quietly do nothing.

    The policy itself ignores anything it does not recognise, so without this check
    a typo would look like a saved change and change nothing at all.
    """
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_claim_age_dayz": "5"}))

    assert "max_claim_age_dayz" in refused.value.message
    assert refused.value.details["values"] == [
        {"name": "max_claim_age_dayz", "message": "The claim policy has no value with this name."}
    ]


def test_two_unknown_names_are_both_named_in_the_complaint() -> None:
    """FR-0.7: a caller is told every name that was not recognised, not just one."""
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"nonsense": "1", "more_nonsense": "2"}))

    assert "nonsense, more_nonsense" in refused.value.message
    assert len(refused.value.details["values"]) == 2


def test_a_value_outside_its_allowed_range_is_refused_with_a_reason() -> None:
    """NFR-4: the person who typed it is told which value, and what was wrong."""
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(Policy(), PolicyUpdate(values={"max_agent_steps": "0"}))

    assert refused.value.status_code == 400
    assert "max_agent_steps" in refused.value.message
    problems = refused.value.details["values"]
    assert [problem["name"] for problem in problems] == ["max_agent_steps"]
    assert problems[0]["message"] != ""


def test_every_refused_value_gets_its_own_complaint() -> None:
    """NFR-4: two bad values produce two complaints, not one vague sentence."""
    with pytest.raises(InvalidRequestError) as refused:
        revise_policy(
            Policy(),
            PolicyUpdate(values={"max_agent_steps": "0", "max_image_analyses_per_run": "0"}),
        )

    named = {problem["name"] for problem in refused.value.details["values"]}
    assert named == {"max_agent_steps", "max_image_analyses_per_run"}


def test_words_can_be_changed_too() -> None:
    """FR-0.2: the claim type handled here is a provisional string, not a rule."""
    revised = revise_policy(
        Policy(), PolicyUpdate(values={"damaged_in_transit_sub_category": "Claim | Damaged"})
    )

    assert revised.damaged_in_transit_sub_category == "Claim | Damaged"


def test_submitting_nothing_gives_back_the_policy_unchanged() -> None:
    """FR-0.7: an empty submission is a no-op rather than an error or a wipe."""
    current = Policy(max_claim_age_days=42)

    revised = revise_policy(current, PolicyUpdate(values={}))

    assert revised == current
