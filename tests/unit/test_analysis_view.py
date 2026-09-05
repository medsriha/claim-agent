"""What the analysis screen is sent, and what it must never have to work out.

The rule these tests defend is that the browser turns a number into a length and does nothing
else (FR-1.21, NFR-2). Anything a chart needs — the scale, the cumulative edges of a stack, the
words beside every figure — has to be in the reply already.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from tests.fixtures.decisions import investigated, screened

from claim_agent.analysis.models import AnalysisView, Panel
from claim_agent.analysis.performance import summarise
from claim_agent.analysis.view import DEFAULT_PERIOD, build, window_for
from claim_agent.domain.decision import DecisionRecord, Proposal, RepAction
from claim_agent.domain.outcome import Recommendation

WINDOW_START = datetime(2026, 3, 2, tzinfo=UTC)
WINDOW_END = datetime(2026, 3, 30, tzinfo=UTC)
GENERATED_AT = datetime(2026, 3, 30, 9, 0, tzinfo=UTC)


Drawn = TypeVar("Drawn")


def view_of(decisions: Sequence[DecisionRecord]) -> AnalysisView:
    """Build the screen's reply from a handful of decisions."""
    return build(summarise(decisions, WINDOW_START, WINDOW_END), DEFAULT_PERIOD, GENERATED_AT)


def drawn(panel: Panel[Drawn]) -> Drawn:
    """The panel's contents, failing the test if there are none.

    A panel that should have held something and did not is the failure worth reading, rather than
    an attribute error twenty lines further down.
    """
    assert panel.data is not None, f"expected a panel with data, got: {panel.empty_reason}"
    return panel.data


# --- Nothing to show is a sentence, not an empty box ---


def test_an_empty_period_says_why_every_panel_is_empty() -> None:
    """An empty box reads as a screen that broke.

    The service is the only thing that knows there is nothing there, so it says so — which is
    also what keeps these sentences out of the screen's own small list of words.
    """
    view = view_of([])

    assert view.approval_trend.data is None
    assert view.approval_trend.empty_reason is not None
    assert view.calibration.data is None
    assert view.gates.empty_reason is not None


def test_a_rate_over_nothing_is_written_as_a_dash_rather_than_zero_per_cent() -> None:
    """Nothing happened is not the same as nothing succeeded."""
    view = view_of([])

    assert view.hero.value == "—"


# --- Every number arrives twice: once to draw, once to read ---


def test_every_point_carries_both_a_value_to_draw_and_the_words_to_read() -> None:
    view = view_of([investigated()])

    point = next(
        one for one in drawn(view.approval_trend).series[0].points if one.value is not None
    )

    assert point.value == 1.0
    assert point.text == "100%"
    assert point.label.startswith("week of ")


def test_a_week_with_nothing_in_it_carries_no_value_so_the_line_breaks() -> None:
    """A week with no claims is not a week at nought per cent.

    Sending zero would draw the line to the floor and read as a collapse in quality.
    """
    view = view_of([investigated()])

    empty_weeks = [
        point for point in drawn(view.approval_trend).series[0].points if point.value is None
    ]

    assert empty_weeks
    assert all(point.text == "—" for point in empty_weeks)


# --- The scale is decided in the service ---


def test_the_axis_and_its_gridlines_are_sent_rather_than_worked_out_in_the_browser() -> None:
    """Where an axis stops is a judgement about the measure, not about pixels."""
    view = view_of([investigated()])

    chart = drawn(view.approval_trend)

    assert chart.domain.minimum == 0.0
    assert chart.domain.maximum == 1.0
    assert [line.label for line in chart.gridlines] == ["0%", "25%", "50%", "75%", "100%"]
    assert chart.ticks


# --- The stack is added up in the service (NFR-2) ---


def test_a_stacked_band_carries_its_cumulative_top_edge_already_added_up() -> None:
    """Four shares that must come to one cannot be trusted to a browser to add.

    Each band's `upper` counts every band below it, so the screen draws the shape between one
    edge and the next and never sums anything.
    """
    decisions = [
        investigated(decision_id="a"),
        investigated(decision_id="b", email_edited=True),
        investigated(
            decision_id="c",
            action=RepAction.APPROVED_WITH_OVERRIDE,
            decided=Proposal(outcome=Recommendation.REQUEST_REP_CLARIFICATION, amount_usd=None),
        ),
        investigated(decision_id="d", action=RepAction.SENT_BACK),
    ]

    bands = drawn(view_of(decisions).intervention_mix).bands
    busiest = next(
        position for position, point in enumerate(bands[0].points) if point.upper is not None
    )
    week = [band.points[busiest].upper for band in bands]

    assert week == [0.25, 0.5, 0.75, 1.0]
    assert week[-1] == 1.0


def test_a_week_with_nothing_investigated_leaves_every_band_empty_together() -> None:
    """All four break at once, so no band is drawn across a week that had nothing in it."""
    bands = drawn(view_of([investigated()]).intervention_mix).bands
    first_week = [band.points[0].upper for band in bands]

    assert first_week == [None, None, None, None]


# --- The calibration panel states both halves and subtracts neither ---


def test_the_calibration_panel_sends_what_was_claimed_and_what_happened_but_not_the_gap() -> None:
    """The difference is a subtraction, and the screen does not tell people what to conclude.

    Whether the measured bar lands inside the claimed band is left for a reader to see.
    """
    view = view_of([investigated(stated_confidence=0.9)])

    band = next(one for one in drawn(view.calibration).bands if one.stated_low == 0.85)

    assert band.band == "85 to 95% sure"
    assert band.stated_high == 0.95
    assert band.agreement.text == "100%"
    assert band.volume.text == "1"
    assert not hasattr(band, "gap")


def test_the_volume_plot_has_a_scale_of_its_own_rather_than_sharing_the_rate_axis() -> None:
    """A rate and a count must never share one scale — the crossing point would mean nothing."""
    view = view_of([investigated()])

    assert drawn(view.calibration).domain.maximum == 1.0
    assert drawn(view.calibration).volume_domain.maximum >= 1.0


# --- Candidate rules are scored, never offered (FR-2.9, FR-3.1) ---


def test_a_candidate_rule_carries_the_services_own_word_for_how_it_scored() -> None:
    """The word is the service's vocabulary, reshaped to read on screen rather than replaced."""
    view = view_of([investigated()])

    assert {row.verdict for row in drawn(view.gates).rows} <= {
        "meets_bar",
        "below_agreement",
        "too_few_decisions",
    }


def test_the_candidate_rules_carry_a_caveat_saying_meeting_the_bar_is_not_permission() -> None:
    """FR-2.9 says a person approving is the only way a claim leaves review.

    A screen that scored rules without saying that would read as offering a switch.
    """
    caveat = drawn(view_of([investigated()]).gates).caveat

    assert "FR-2.9" in caveat
    assert "PROVISIONAL" in caveat


# --- The money and what it rests on ---


def test_every_assumption_behind_the_money_is_shown_and_marked_provisional() -> None:
    """A total nobody can see the basis of is a total nobody can argue with."""
    view = view_of([investigated()])

    assert view.assumptions
    assert all(one.marker == "PROVISIONAL" for one in view.assumptions)
    assert all(one.description for one in view.assumptions)


def test_money_is_written_out_by_the_service_so_nothing_in_the_browser_parses_it() -> None:
    view = view_of([investigated()])

    valued = next(one for one in view.savings if one.label == "Estimated value of time saved")

    assert valued.value.startswith("$")


def test_the_dashboard_average_is_an_average_rather_than_the_middle_review() -> None:
    decisions = [
        investigated(decision_id="a", rep_minutes=5),
        investigated(decision_id="b", rep_minutes=7),
        investigated(decision_id="c", rep_minutes=300),
    ]

    view = view_of(decisions)
    average = next(one for one in view.figures if one.label == "Average review time")

    assert average.value == "104 min"
    assert drawn(view.review_time).summary.startswith("Representatives spent an average of 104 min")


# --- The window ---


def test_the_window_starts_on_a_week_boundary_so_no_bar_covers_a_part_week() -> None:
    """A first bar covering two days beside bars covering seven understates every trend."""
    starts_at, ends_at = window_for("four_weeks", datetime(2026, 3, 25, 14, 0, tzinfo=UTC))

    assert starts_at == datetime(2026, 3, 2, tzinfo=UTC)
    assert ends_at == datetime(2026, 3, 25, 14, 0, tzinfo=UTC)


def test_an_unknown_period_falls_back_to_the_default_rather_than_failing() -> None:
    """A way of looking at the past is not the kind of thing where being wrong is dangerous."""
    now = datetime(2026, 3, 25, 14, 0, tzinfo=UTC)

    assert window_for("last_tuesday", now) == window_for(DEFAULT_PERIOD, now)


def test_the_reply_says_which_period_it_used_and_which_ones_it_offers() -> None:
    """The screen never works out a date, so it needs the service to name what it asked for."""
    view = view_of([screened()])

    assert view.period_label.startswith("Data period: ")
    assert [one.key for one in view.presets if one.applied] == [DEFAULT_PERIOD]
