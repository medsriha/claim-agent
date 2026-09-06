from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.fixtures.decisions import investigated, screened

from claim_agent.analysis.performance import (
    band_for,
    share,
    summarise,
    tally_of,
    value_band_for,
    week_starting,
)
from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.outcome import Recommendation

WINDOW_START = datetime(2026, 3, 2, tzinfo=UTC)
WINDOW_END = datetime(2026, 3, 30, tzinfo=UTC)


def test_a_share_of_nothing_is_nothing_rather_than_zero() -> None:
    assert share(0, 0) is None
    assert share(0, 4) == 0.0
    assert share(3, 4) == 0.75


def test_a_band_excludes_its_top_edge_so_two_bands_never_claim_one_figure() -> None:
    bands = [("low", 0.0, 0.5), ("high", 0.5, 1.0)]

    assert band_for(0.49, bands) == "low"
    assert band_for(0.5, bands) == "high"


def test_the_last_band_includes_its_top_edge_so_complete_certainty_has_somewhere_to_go() -> None:
    bands = [("low", 0.0, 0.5), ("high", 0.5, 1.0)]

    assert band_for(1.0, bands) == "high"


def test_an_order_nobody_could_price_falls_into_no_value_band() -> None:
    assert value_band_for(None) is None
    assert value_band_for(Decimal("99.99")) == "under_100"
    assert value_band_for(Decimal("100.00")) == "100_to_500"
    assert value_band_for(Decimal("500.00")) == "500_and_over"


def test_the_four_ways_a_decision_can_go_add_up_to_the_total_exactly_once() -> None:
    decisions = [
        investigated(),
        investigated(email_edited=True),
        investigated(
            action=RepAction.APPROVED_WITH_OVERRIDE,
            decided=Proposal(outcome=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None),
        ),
        investigated(action=RepAction.SENT_BACK),
    ]

    tally = tally_of(decisions)

    assert tally.decisions == 4
    assert tally.direct_approvals == 1
    assert tally.wording_only == 1
    assert tally.substance_changed == 1
    assert tally.sent_back == 1
    assert (
        tally.direct_approvals + tally.wording_only + tally.substance_changed + tally.sent_back
        == tally.decisions
    )


def test_a_changed_decision_that_was_also_reworded_is_counted_as_changed_only() -> None:
    tally = tally_of(
        [
            investigated(
                action=RepAction.APPROVED_WITH_OVERRIDE,
                email_edited=True,
                decided=Proposal(outcome=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None),
            )
        ]
    )

    assert tally.substance_changed == 1
    assert tally.wording_only == 0


def test_stopped_claims_and_investigated_products_are_counted_apart() -> None:
    decisions = [
        screened(decision_id="DEC-CASE-9002-01"),
        screened(decision_id="DEC-CASE-9003-01"),
        investigated(action=RepAction.SENT_BACK),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)

    assert performance.totals.overall.decisions == 3
    assert performance.totals.screening.decisions == 2
    assert performance.totals.screening.direct_approvals == 2
    assert performance.totals.investigation.decisions == 1
    assert performance.totals.investigation.direct_approvals == 0


def test_a_stopped_claim_is_left_out_of_the_confidence_comparison() -> None:
    performance = summarise([screened()], WINDOW_START, WINDOW_END)

    assert sum(band.decisions for band in performance.confidence_bands) == 0


def test_a_week_is_cut_on_monday_in_utc_wherever_the_machine_is() -> None:
    wednesday = datetime(2026, 3, 4, 23, 30, tzinfo=UTC)

    assert week_starting(wednesday) == datetime(2026, 3, 2, tzinfo=UTC)


def test_a_week_nobody_decided_anything_in_still_appears_as_a_gap() -> None:
    performance = summarise([], WINDOW_START, WINDOW_END)

    assert len(performance.weeks) == 4
    assert all(week.tallies.overall.decisions == 0 for week in performance.weeks)
    assert all(week.median_rep_minutes is None for week in performance.weeks)


def test_a_decision_outside_the_window_is_ignored_rather_than_counted() -> None:
    performance = summarise(
        [investigated(decided_at=WINDOW_END + timedelta(days=1))], WINDOW_START, WINDOW_END
    )

    assert performance.totals.overall.decisions == 0


def test_the_middle_review_time_is_used_rather_than_the_average() -> None:
    decisions = [
        investigated(decision_id="a", rep_minutes=5),
        investigated(decision_id="b", rep_minutes=7),
        investigated(decision_id="c", rep_minutes=300),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)

    assert performance.median_rep_minutes == 7


def test_savings_charge_nothing_for_a_claim_the_quick_checks_stopped() -> None:
    performance = summarise([screened(rep_minutes=3)], WINDOW_START, WINDOW_END)

    assert performance.savings.ai_cost_usd == Decimal("0.00")
    assert performance.savings.rep_hours_saved == Decimal("0.05")
    assert performance.savings.net_saving_usd == Decimal("2.50")
    assert isinstance(performance.savings.net_saving_usd, Decimal)


def test_a_review_that_took_longer_than_doing_it_by_hand_shows_a_loss() -> None:
    performance = summarise([investigated(rep_minutes=82)], WINDOW_START, WINDOW_END)

    assert performance.savings.rep_hours_saved < 0
    assert performance.savings.net_saving_usd < 0


def test_a_rule_scored_on_too_few_decisions_never_meets_the_bar() -> None:
    performance = summarise([investigated(stated_confidence=0.99)], WINDOW_START, WINDOW_END)

    assert [gate for gate in performance.gates if gate.meets_bar] == []


def test_every_value_band_is_scored_even_when_nothing_fell_into_it() -> None:
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert {gate.value_band for gate in performance.gates} == {
        "under_100",
        "100_to_500",
        "500_and_over",
    }


def test_no_candidate_rule_is_built_below_the_level_the_rules_already_withhold_payment() -> None:
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert "below_the_bar" not in {gate.confidence_band for gate in performance.gates}


def test_claims_are_cut_by_things_known_before_anybody_looks_at_them() -> None:
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert [group.name for group in performance.readiness] == [
        "What the merchant reported",
        "What they said caused it",
        "Who carried the parcel",
        "How sure the system said it was",
    ]


def test_readiness_counts_only_untouched_decisions() -> None:
    decisions = [
        investigated(decision_id="a"),
        investigated(decision_id="b", email_edited=True),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)
    reported = next(
        group for group in performance.readiness if group.name == "What the merchant reported"
    )
    [only] = reported.segments

    assert only.decisions == 2
    assert only.direct_approvals == 1
    assert only.readiness == 0.5


def test_a_cut_whose_parts_all_behave_alike_reports_a_spread_of_nothing() -> None:
    decisions = [
        investigated(decision_id="a", carrier="USPS"),
        investigated(decision_id="b", carrier="UniUni"),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)
    carriers = next(
        group for group in performance.readiness if group.name == "Who carried the parcel"
    )

    assert carriers.spread == 0.0


def test_a_cut_with_only_one_part_has_no_spread_to_report() -> None:
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)
    reported = next(
        group for group in performance.readiness if group.name == "What the merchant reported"
    )

    assert reported.spread is None


def test_the_parts_of_a_cut_come_back_readiest_first() -> None:
    decisions = [
        investigated(decision_id="a", carrier="UniUni", email_edited=True),
        investigated(decision_id="b", carrier="USPS"),
        investigated(decision_id="c", carrier="USPS"),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)
    carriers = next(
        group for group in performance.readiness if group.name == "Who carried the parcel"
    )

    assert [one.name for one in carriers.segments] == ["USPS", "UniUni"]


def test_a_claim_with_nothing_recorded_about_it_is_left_out_rather_than_grouped() -> None:
    performance = summarise([investigated(carrier=None)], WINDOW_START, WINDOW_END)
    carriers = next(
        group for group in performance.readiness if group.name == "Who carried the parcel"
    )

    assert carriers.segments == ()


def test_stopped_claims_are_left_out_of_the_readiness_cuts() -> None:
    performance = summarise(
        [screened(), screened(decision_id="DEC-CASE-9003-01")], WINDOW_START, WINDOW_END
    )

    assert all(
        segment.decisions == 0 for group in performance.readiness for segment in group.segments
    )


def test_the_same_decisions_in_a_different_order_produce_the_same_figures() -> None:
    decisions = [
        investigated(decision_id="a", rep_minutes=4),
        screened(decision_id="b", rep_minutes=2),
        investigated(decision_id="c", rep_minutes=9, action=RepAction.SENT_BACK),
    ]

    assert summarise(decisions, WINDOW_START, WINDOW_END) == summarise(
        list(reversed(decisions)), WINDOW_START, WINDOW_END
    )
