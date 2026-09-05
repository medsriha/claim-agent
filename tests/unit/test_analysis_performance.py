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


# --- A rate over nothing has no answer, and must never be reported as zero ---


def test_a_share_of_nothing_is_nothing_rather_than_zero() -> None:
    """Nought out of nought is a question with no answer.

    Reporting it as 0% would draw a line to the floor of a chart, which reads as a collapse in
    quality when the truth is that nobody decided anything that week.
    """
    assert share(0, 0) is None
    assert share(0, 4) == 0.0
    assert share(3, 4) == 0.75


# --- Putting a figure in a band ---


def test_a_band_excludes_its_top_edge_so_two_bands_never_claim_one_figure() -> None:
    bands = [("low", 0.0, 0.5), ("high", 0.5, 1.0)]

    assert band_for(0.49, bands) == "low"
    assert band_for(0.5, bands) == "high"


def test_the_last_band_includes_its_top_edge_so_complete_certainty_has_somewhere_to_go() -> None:
    """Without this, a claim the system was entirely sure of would fall out of every band."""
    bands = [("low", 0.0, 0.5), ("high", 0.5, 1.0)]

    assert band_for(1.0, bands) == "high"


def test_an_order_nobody_could_price_falls_into_no_value_band() -> None:
    """An unknown order value is left out rather than guessed into the cheapest band.

    It is not the same as an order worth nothing, and putting it in the bottom band would score a
    candidate rule on claims nobody could price.
    """
    assert value_band_for(None) is None
    assert value_band_for(Decimal("99.99")) == "under_100"
    assert value_band_for(Decimal("100.00")) == "100_to_500"
    assert value_band_for(Decimal("500.00")) == "500_and_over"


# --- The four ways a decision can go, counted once each ---


def test_the_four_ways_a_decision_can_go_add_up_to_the_total_exactly_once() -> None:
    """A stacked chart of the four is only honest if nothing can land in two of them."""
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
    """Substance beats wording, so the bands stay exclusive and nothing is counted twice."""
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


# --- The two populations (FR-C.1) ---


def test_stopped_claims_and_investigated_products_are_counted_apart() -> None:
    """FR-C.1's two kinds of decision answer different questions about automation.

    A stopped claim costs no AI and is almost always accepted. Blending it into one figure would
    make the advice look better than it is, so every total is kept three ways.
    """
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
    """Nothing was asked of the AI, so putting it in a band would invent an opinion."""
    performance = summarise([screened()], WINDOW_START, WINDOW_END)

    assert sum(band.decisions for band in performance.confidence_bands) == 0


# --- Weeks ---


def test_a_week_is_cut_on_monday_in_utc_wherever_the_machine_is() -> None:
    """NFR-1: the same data must bucket the same way on any machine."""
    wednesday = datetime(2026, 3, 4, 23, 30, tzinfo=UTC)

    assert week_starting(wednesday) == datetime(2026, 3, 2, tzinfo=UTC)


def test_a_week_nobody_decided_anything_in_still_appears_as_a_gap() -> None:
    """Weeks come from the calendar, not from the decisions.

    Leaving an empty week out would close the space up and make a quiet fortnight look like a
    busy one. The week is present and its rate is nothing at all, which a chart draws as a gap.
    """
    performance = summarise([], WINDOW_START, WINDOW_END)

    assert len(performance.weeks) == 4
    assert all(week.tallies.overall.decisions == 0 for week in performance.weeks)
    assert all(week.median_rep_minutes is None for week in performance.weeks)


def test_a_decision_outside_the_window_is_ignored_rather_than_counted() -> None:
    """A caller that reads a little too widely still gets a correct answer."""
    performance = summarise(
        [investigated(decided_at=WINDOW_END + timedelta(days=1))], WINDOW_START, WINDOW_END
    )

    assert performance.totals.overall.decisions == 0


# --- Review time ---


def test_the_middle_review_time_is_used_rather_than_the_average() -> None:
    """One claim left in a queue over a weekend would drag an average somewhere no review was."""
    decisions = [
        investigated(decision_id="a", rep_minutes=5),
        investigated(decision_id="b", rep_minutes=7),
        investigated(decision_id="c", rep_minutes=300),
    ]

    performance = summarise(decisions, WINDOW_START, WINDOW_END)

    assert performance.median_rep_minutes == 7


# --- Money (FR-1.21, NFR-2) ---


def test_savings_charge_nothing_for_a_claim_the_quick_checks_stopped() -> None:
    """A stopped claim cost no AI, so no AI cost is charged against it.

    Every figure is a `Decimal` throughout: whole minutes divided by sixty and multiplied by a
    rate, so no amount of money in this system has ever been a floating-point number.
    """
    performance = summarise([screened(rep_minutes=3)], WINDOW_START, WINDOW_END)

    assert performance.savings.ai_cost_usd == Decimal("0.00")
    assert performance.savings.rep_hours_saved == Decimal("0.05")
    assert performance.savings.net_saving_usd == Decimal("2.50")
    assert isinstance(performance.savings.net_saving_usd, Decimal)


def test_a_review_that_took_longer_than_doing_it_by_hand_shows_a_loss() -> None:
    """The arithmetic is not clamped at zero.

    A system that costs more time than it saves must be able to say so, or the screen could only
    ever report good news.
    """
    performance = summarise([investigated(rep_minutes=82)], WINDOW_START, WINDOW_END)

    assert performance.savings.rep_hours_saved < 0
    assert performance.savings.net_saving_usd < 0


# --- Candidate rules (FR-C.7, FR-2.9) ---


def test_a_rule_scored_on_too_few_decisions_never_meets_the_bar() -> None:
    """Agreement of 100% across one claim is not evidence of anything."""
    performance = summarise([investigated(stated_confidence=0.99)], WINDOW_START, WINDOW_END)

    assert [gate for gate in performance.gates if gate.meets_bar] == []


def test_every_value_band_is_scored_even_when_nothing_fell_into_it() -> None:
    """A reader should see that a band is untested rather than infer it from a missing row."""
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert {gate.value_band for gate in performance.gates} == {
        "under_100",
        "100_to_500",
        "500_and_over",
    }


def test_no_candidate_rule_is_built_below_the_level_the_rules_already_withhold_payment() -> None:
    """FR-1.15 already refuses to recommend paying under 70% sure.

    A rule letting claims through below that would be the system arguing with itself.
    """
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert "below_the_bar" not in {gate.confidence_band for gate in performance.gates}


# --- Which claims come back ready ---


def test_claims_are_cut_by_things_known_before_anybody_looks_at_them() -> None:
    """The panel answers "which claims will need a person", so it cuts by what arrives with them.

    What the merchant said was damaged, what they said caused it, and who carried the parcel are
    all known up front. Cutting by what the investigation went on to recommend would only describe
    work already done, which is why no such cut is offered.
    """
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)

    assert [group.name for group in performance.readiness] == [
        "What the merchant reported",
        "What they said caused it",
        "Who carried the parcel",
        "How sure the system said it was",
    ]


def test_readiness_counts_only_untouched_decisions() -> None:
    """ "Ready" is the strictest reading: nothing changed, not even a word of the email.

    A rewritten email is not a disagreement, but it is still work somebody had to do, and this
    figure is about which claims need nobody.
    """
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
    """A flat group is a finding — that way of sorting claims does not help — not a gap.

    Reporting how far apart the parts are is what lets the screen say so, rather than leaving
    somebody to eyeball four bars of much the same length.
    """
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
    """Nothing to compare it against, which is not the same as the parts behaving alike."""
    performance = summarise([investigated()], WINDOW_START, WINDOW_END)
    reported = next(
        group for group in performance.readiness if group.name == "What the merchant reported"
    )

    assert reported.spread is None


def test_the_parts_of_a_cut_come_back_readiest_first() -> None:
    """These properties have no order of their own, so the measure gives them one.

    A group read as a run from the claims that look after themselves down to the ones that do not
    is the whole point; unordered bars leave a reader doing the sorting.
    """
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
    """A part named after a gap in the data would look like a kind of claim."""
    performance = summarise([investigated(carrier=None)], WINDOW_START, WINDOW_END)
    carriers = next(
        group for group in performance.readiness if group.name == "Who carried the parcel"
    )

    assert carriers.segments == ()


def test_stopped_claims_are_left_out_of_the_readiness_cuts() -> None:
    """They are decided by fixed rules and almost always accepted.

    Folding them in would drop a large, easy population into every cut and flatten the very
    differences the panel exists to show.
    """
    performance = summarise(
        [screened(), screened(decision_id="DEC-CASE-9003-01")], WINDOW_START, WINDOW_END
    )

    assert all(
        segment.decisions == 0 for group in performance.readiness for segment in group.segments
    )


# --- The same data twice (NFR-1) ---


def test_the_same_decisions_in_a_different_order_produce_the_same_figures() -> None:
    """Nothing here may depend on the order rows came back in."""
    decisions = [
        investigated(decision_id="a", rep_minutes=4),
        screened(decision_id="b", rep_minutes=2),
        investigated(decision_id="c", rep_minutes=9, action=RepAction.SENT_BACK),
    ]

    assert summarise(decisions, WINDOW_START, WINDOW_END) == summarise(
        list(reversed(decisions)), WINDOW_START, WINDOW_END
    )
