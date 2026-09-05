"""Turning the figures into what the screen draws.

Everything a person reads on the analysis screen is written here: the titles, the sentences under
the charts, the words in the tiles, and the already-written-out version of every number. That is
deliberate. The screen is meant to add labels and nothing else, so anything resembling a sentence
has to come from the service, and this is the service's mouth.

It is also where every number becomes two things: the value a chart uses to place a mark, and the
text a person reads. Nothing downstream turns one into the other.

Nothing here decides anything about a claim, and nothing here does arithmetic on money — the
amounts arrive already worked out and are only written out with a currency sign in front.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from claim_agent.analysis import assumptions
from claim_agent.analysis.assumptions import CONFIDENCE_BANDS
from claim_agent.analysis.models import (
    AnalysisView,
    Assumption,
    Band,
    BandPoint,
    BarChart,
    Calibration,
    CalibrationBand,
    Domain,
    Figure,
    GateRow,
    GateTable,
    Gridline,
    Panel,
    Point,
    Preset,
    Readiness,
    ReadinessGroup,
    ReadinessRow,
    Series,
    StackedChart,
    TimeChart,
)
from claim_agent.analysis.performance import Performance, Tally, share, week_starting

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# How long each stretch of time the screen can ask for is, in whole weeks, so that every bucket
# on a chart is a complete week and none of them is a stub.
PERIODS: tuple[tuple[str, str, int], ...] = (
    ("four_weeks", "4 weeks", 4),
    ("thirteen_weeks", "13 weeks", 13),
    ("twelve_months", "12 months", 52),
)

DEFAULT_PERIOD = "twelve_months"

_RATE_GRIDLINES = (
    Gridline(at=0.0, label="0%"),
    Gridline(at=0.25, label="25%"),
    Gridline(at=0.5, label="50%"),
    Gridline(at=0.75, label="75%"),
    Gridline(at=1.0, label="100%"),
)

_RATE_DOMAIN = Domain(minimum=0.0, maximum=1.0)


def _day_text(moment: datetime) -> str:
    """Write a date the same way on every machine — "4 September 2026".

    The browser's own date formatting changes with how the machine is set up, so the same period
    would read differently to two people. Every other date this system shows is written out by
    hand for the same reason.
    """
    at_utc = moment.astimezone(UTC)
    return f"{at_utc.day} {_MONTHS[at_utc.month - 1]} {at_utc.year}"


def _week_text(moment: datetime) -> str:
    """Name a week by the day it starts — "week of 4 Sep"."""
    at_utc = moment.astimezone(UTC)
    return f"week of {at_utc.day} {_SHORT_MONTHS[at_utc.month - 1]}"


def _count_text(number: int) -> str:
    """Write a whole number with separators, so four figures can be read at a glance."""
    return f"{number:,}"


def _percent_text(rate: float | None) -> str:
    """Write a rate as a percentage, or a dash when there is no rate to write.

    A dash rather than "0%": nothing happened is not the same as nothing succeeded, and this is
    the distinction the whole screen is careful about.
    """
    if rate is None:
        return "—"
    return f"{round(rate * 100)}%"


def _minutes_text(minutes: float | None) -> str:
    """Write a length of time in minutes, or a dash when nobody reviewed anything."""
    if minutes is None:
        return "—"
    if minutes == int(minutes):
        return f"{int(minutes)} min"
    return f"{minutes:.1f} min"


def _money_text(amount: Decimal) -> str:
    """Write an amount already worked out, with a currency sign and separators.

    The amount arrives as a `Decimal` that was worked out elsewhere. Nothing here adds, multiplies
    or rounds it; it is only written down.
    """
    return f"${amount:,.2f}"


def _hours_text(hours: Decimal) -> str:
    """Write a number of hours already worked out."""
    return f"{hours:,.0f} hours"


def _nice_ceiling(largest: float) -> float:
    """A round number at or above the largest value, for the top of an axis.

    Axes that stop at the largest value leave the highest mark touching the top of the chart,
    where it reads as clipped. Rounding up to something a person would say out loud — twenty, not
    18.4 — also makes the gridlines mean something.
    """
    if largest <= 0:
        return 1.0
    step = 1.0
    while step * 10 < largest:
        step *= 10
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        candidate = step * multiple
        if candidate >= largest:
            return candidate
    return step * 10


def _even_gridlines(maximum: float, count: int, suffix: str) -> tuple[Gridline, ...]:
    """Evenly spaced rules from nothing up to the top of the axis."""
    return tuple(
        Gridline(
            at=maximum * position / count,
            label=f"{round(maximum * position / count):,}{suffix}",
        )
        for position in range(count + 1)
    )


def _month_ticks(week_starts: tuple[datetime, ...]) -> tuple[int, ...]:
    """Which weeks get a word under them: the first week of every other month.

    Every month would crowd a year of weeks into unreadable overlap, and every week would be far
    worse. The first and last are always included so a reader can see where the period begins and
    ends.
    """
    firsts = [
        position
        for position, start in enumerate(week_starts)
        if position == 0 or start.month != week_starts[position - 1].month
    ]
    spacing = 2 if len(firsts) > 7 else 1
    chosen = {firsts[position] for position in range(0, len(firsts), spacing)}
    if week_starts:
        chosen.add(len(week_starts) - 1)
    return tuple(sorted(chosen))


def _rate_point(part: int, whole: int, label: str) -> Point:
    """One point on a rate chart, carrying both the position and the words."""
    rate = share(part, whole)
    return Point(value=rate, text=_percent_text(rate), label=label)


def resolve_period(period: str) -> str:
    """The period actually used, which is the default when the one asked for is not offered.

    Resolved once, here, so that the window and the list of choices can never disagree — the
    screen showing a year of figures with nothing marked as chosen would leave a reader unable to
    say what they were looking at.
    """
    known = {key for key, _label, _weeks in PERIODS}
    return period if period in known else DEFAULT_PERIOD


def window_for(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Work out which stretch of time a named period covers.

    The start is pulled back to the beginning of a week so that every bucket on a chart is a whole
    week. That makes the period slightly longer than its name suggests, which is the right trade:
    a first bar covering two days sitting beside bars covering seven would understate the start of
    every trend on the screen.

    Args:
        period: One of the keys in `PERIODS`. An unknown one falls back to the default rather than
            failing, because a period is a way of looking at the data and not an instruction that
            could be dangerous to get wrong.
        now: The moment the request arrived, in UTC.

    Returns:
        The first moment covered and the first moment not covered.
    """
    resolved = resolve_period(period)
    weeks = next(count for key, _label, count in PERIODS if key == resolved)
    return week_starting(now - timedelta(weeks=weeks - 1)), now


def _presets(applied: str) -> tuple[Preset, ...]:
    """Every stretch of time the screen offers, saying which one is in force."""
    return tuple(
        Preset(key=key, label=label, applied=key == applied) for key, label, _weeks in PERIODS
    )


def _approval_trend(performance: Performance) -> Panel[TimeChart]:
    """How often each population went out exactly as the system produced it, week by week.

    Two lines rather than one, because the two populations are the whole argument: a claim the
    quick checks stopped is decided by fixed rules and almost always accepted, and folding it in
    with the investigated claims would hide how the advice is really doing.
    """
    if performance.totals.overall.decisions == 0:
        return Panel(
            empty_reason=(
                "No decisions were reviewed during this period, so there is no acceptance rate "
                "to show."
            ),
            data=None,
        )
    starts = tuple(week.starts_at for week in performance.weeks)
    return Panel(
        empty_reason=None,
        data=TimeChart(
            title="Recommendations accepted without changes, by week",
            y_label="Acceptance rate",
            domain=_RATE_DOMAIN,
            gridlines=_RATE_GRIDLINES,
            ticks=_month_ticks(starts),
            series=(
                Series(
                    name="AI-investigated products",
                    points=tuple(
                        _rate_point(
                            week.tallies.investigation.direct_approvals,
                            week.tallies.investigation.decisions,
                            _week_text(week.starts_at),
                        )
                        for week in performance.weeks
                    ),
                ),
                Series(
                    name="Claims stopped by eligibility checks",
                    points=tuple(
                        _rate_point(
                            week.tallies.screening.direct_approvals,
                            week.tallies.screening.decisions,
                            _week_text(week.starts_at),
                        )
                        for week in performance.weeks
                    ),
                ),
            ),
            summary=(
                "Representatives accepted "
                f"{_percent_text(share(performance.totals.investigation.direct_approvals, performance.totals.investigation.decisions))}"
                " of AI-investigated product recommendations and "
                f"{_percent_text(share(performance.totals.screening.direct_approvals, performance.totals.screening.decisions))}"
                " of eligibility-check decisions without changes."
            ),
        ),
    )


# The four ways an investigated product can go, bottom to top, each paired with the way to read
# its count off a tally. Named functions rather than field names looked up by string: a mistyped
# field would be a chart that silently drew the wrong band.
_MIX_BANDS: tuple[tuple[str, Callable[[Tally], int]], ...] = (
    ("Accepted without changes", lambda tally: tally.direct_approvals),
    ("Email wording changed only", lambda tally: tally.wording_only),
    ("Outcome or reimbursement changed", lambda tally: tally.substance_changed),
    ("Sent back for reinvestigation", lambda tally: tally.sent_back),
)


def _intervention_mix(performance: Performance) -> Panel[StackedChart]:
    """How far representatives went, week by week, as four shares of the whole.

    The four are worked out so that they cover every decision exactly once, and each band's top
    edge is sent already added up. The browser draws the shapes between the edges and never sums
    anything, so four shares that must come to one cannot drift apart on screen.
    """
    if performance.totals.investigation.decisions == 0:
        return Panel(
            empty_reason=(
                "No products were investigated during this period, so there are no review "
                "outcomes to show."
            ),
            data=None,
        )
    starts = tuple(week.starts_at for week in performance.weeks)
    bands: list[Band] = []
    running: list[Callable[[Tally], int]] = []
    for label, count_of in _MIX_BANDS:
        running.append(count_of)
        points: list[BandPoint] = []
        for week in performance.weeks:
            tally = week.tallies.investigation
            if tally.decisions == 0:
                points.append(BandPoint(upper=None, text="—", label=_week_text(week.starts_at)))
                continue
            below = sum(read(tally) for read in running)
            own = count_of(tally)
            points.append(
                BandPoint(
                    upper=below / tally.decisions,
                    text=_percent_text(own / tally.decisions),
                    label=_week_text(week.starts_at),
                )
            )
        bands.append(Band(name=label, points=tuple(points)))

    totals: Tally = performance.totals.investigation
    return Panel(
        empty_reason=None,
        data=StackedChart(
            title="How representatives handled AI recommendations",
            y_label="Share of reviewed products",
            domain=_RATE_DOMAIN,
            gridlines=_RATE_GRIDLINES,
            ticks=_month_ticks(starts),
            bands=tuple(bands),
            summary=(
                "Of investigated products, "
                f"{_percent_text(share(totals.direct_approvals, totals.decisions))} were accepted "
                "without changes, "
                f"{_percent_text(share(totals.wording_only, totals.decisions))} had only the "
                "merchant email wording changed, "
                f"{_percent_text(share(totals.substance_changed, totals.decisions))} had the "
                "recommended outcome or reimbursement changed, and "
                f"{_percent_text(share(totals.sent_back, totals.decisions))} were sent back for "
                "another investigation."
            ),
        ),
    )


def _calibration(performance: Performance) -> Panel[Calibration]:
    """What the system claimed about itself, against what representatives then did."""
    banded = [band for band in performance.confidence_bands if band.decisions > 0]
    if not banded:
        return Panel(
            empty_reason=(
                "No investigated products during this period included an AI confidence score, "
                "so confidence cannot be compared with representative decisions."
            ),
            data=None,
        )
    busiest = max(band.decisions for band in performance.confidence_bands)
    ceiling = _nice_ceiling(float(busiest))
    return Panel(
        empty_reason=None,
        data=Calibration(
            title="AI confidence compared with representative acceptance",
            bands=tuple(
                CalibrationBand(
                    band=_confidence_label(band.name),
                    stated_low=band.stated_low,
                    stated_high=band.stated_high,
                    agreement=Point(
                        value=band.agreement,
                        text=_percent_text(band.agreement),
                        label=_confidence_label(band.name),
                    ),
                    volume=Point(
                        value=float(band.decisions),
                        text=_count_text(band.decisions),
                        label=_confidence_label(band.name),
                    ),
                )
                for band in performance.confidence_bands
            ),
            domain=_RATE_DOMAIN,
            gridlines=_RATE_GRIDLINES,
            volume_domain=Domain(minimum=0.0, maximum=ceiling),
            summary=(
                "Each bar shows the percentage of recommendations accepted without changes. "
                "The shaded range shows the AI confidence for that group. When a bar falls "
                "below its shaded range, actual acceptance was lower than the stated confidence."
            ),
        ),
    )


def _readiness_label(group: str, segment: str) -> str:
    """What to call one part of a cut.

    Everything but the confidence bands is already ShipBob's own words for a real thing — a
    carrier, a kind of damage — and is passed through untouched. The bands are ours, and are
    named by the range they cover so that nobody has to look up what "fair" means.
    """
    if group == "How sure the system said it was":
        return _confidence_label(segment)
    clearer = {
        "Both product and shipping box damaged": "Product and shipping box both damaged",
        "Damage due to poor/bad packaging": "Poor packaging",
        "Damage due to carrier mishandling": "Carrier mishandling",
    }
    return clearer.get(segment, segment)


def _readiness_group_label(group: str) -> str:
    """Give each claim grouping a short heading that says exactly what it compares."""
    return {
        "How sure the system said it was": "AI confidence",
        "What the merchant reported": "Reported damage pattern",
        "Who carried the parcel": "Shipping carrier",
        "What they said caused it": "Reported damage cause",
    }.get(group, group)


def _confidence_label(name: str) -> str:
    """Name a confidence band by the range it actually covers.

    The bands have short names in the settings — "fair", "high" — and those names mean nothing to
    anybody reading a screen. "Below the bar" is worse than nothing: it refers to the level below
    which the rules already refuse to recommend paying (FR-1.15), which is knowledge nobody
    outside this codebase has.

    So a band is labelled with its own edges. The label is built from the numbers rather than
    written beside them, which is what stops the two disagreeing if a band is ever moved.
    """
    for band, low, high in CONFIDENCE_BANDS:
        if band != name:
            continue
        if low <= 0.0:
            return f"Under {round(high * 100)}% sure"
        if high >= 1.0:
            return f"{round(low * 100)}% sure or more"
        return f"{round(low * 100)} to {round(high * 100)}% sure"
    return name


def _spread_text(spread: float | None) -> str:
    """Say in words how much a cut separates claims, so a flat one reads as a finding.

    A group whose parts all come back ready about as often is not noise to be squinted at. It is
    an answer, and the answer is that this way of sorting claims does not help.
    """
    if spread is None:
        return "Not enough decisions to compare"
    points = round(spread * 100)
    point_word = "point" if points == 1 else "points"
    return f"{points} percentage {point_word} between highest and lowest"


def _readiness(performance: Performance) -> Panel[Readiness]:
    """Which kinds of claim came back ready to send, and which needed a person."""
    if performance.totals.investigation.decisions == 0:
        return Panel(
            empty_reason=(
                "No products were investigated during this period, so acceptance rates cannot "
                "be compared by claim characteristic."
            ),
            data=None,
        )
    return Panel(
        empty_reason=None,
        data=Readiness(
            title="Acceptance rate by claim characteristic",
            domain=_RATE_DOMAIN,
            groups=tuple(
                ReadinessGroup(
                    name=_readiness_group_label(group.name),
                    spread_text=_spread_text(group.spread),
                    rows=tuple(
                        ReadinessRow(
                            label=_readiness_label(group.name, segment.name),
                            ready=Point(
                                value=segment.readiness,
                                text=_percent_text(segment.readiness),
                                label=segment.name,
                            ),
                            volume=Point(
                                value=float(segment.decisions),
                                text=_count_text(segment.decisions),
                                label=segment.name,
                            ),
                        )
                        for segment in group.segments
                    ),
                )
                for group in sorted(
                    performance.readiness,
                    key=lambda one: (one.spread is None, -(one.spread or 0.0)),
                )
            ),
            summary=(
                "Each bar shows the percentage of AI recommendations accepted without changes. "
                "The decision count shows the sample size. Sections are ordered by the gap "
                "between their highest and lowest acceptance rates."
            ),
        ),
    )


def _disagreement(performance: Performance) -> Panel[BarChart]:
    """Which of the three proposed actions representatives changed most often."""
    if performance.totals.investigation.decisions == 0:
        return Panel(
            empty_reason=(
                "No products were investigated during this period, so there are no "
                "recommendations to compare."
            ),
            data=None,
        )
    return Panel(
        empty_reason=None,
        data=BarChart(
            title="Recommendation change rate by outcome",
            domain=_RATE_DOMAIN,
            gridlines=_RATE_GRIDLINES,
            bars=tuple(
                Point(
                    value=stats.disagreement,
                    text=_percent_text(stats.disagreement),
                    label=stats.outcome.value,
                )
                for stats in performance.outcomes
            ),
            summary=(
                "Each bar shows the percentage of recommendations a representative changed or "
                "sent back. Outcomes with no recommendations have no bar."
            ),
        ),
    )


def _review_time(performance: Performance) -> Panel[TimeChart]:
    """Average representative review time, week by week."""
    if performance.totals.overall.decisions == 0:
        return Panel(
            empty_reason="No decisions were reviewed during this period.",
            data=None,
        )
    weekly_averages = tuple(week.tallies.overall.average_rep_minutes for week in performance.weeks)
    longest = max(
        (minutes for minutes in weekly_averages if minutes is not None),
        default=1.0,
    )
    ceiling = _nice_ceiling(longest)
    starts = tuple(week.starts_at for week in performance.weeks)
    return Panel(
        empty_reason=None,
        data=TimeChart(
            title="Average review time by week",
            y_label="Average minutes per decision",
            domain=Domain(minimum=0.0, maximum=ceiling),
            gridlines=_even_gridlines(ceiling, 4, ""),
            ticks=_month_ticks(starts),
            series=(
                Series(
                    name="Average review time",
                    points=tuple(
                        Point(
                            value=average,
                            text=_minutes_text(average),
                            label=_week_text(week.starts_at),
                        )
                        for week, average in zip(performance.weeks, weekly_averages, strict=True)
                    ),
                ),
            ),
            summary=(
                "Representatives spent an average of "
                f"{_minutes_text(performance.totals.overall.average_rep_minutes)} reviewing each "
                "decision during this period."
            ),
        ),
    )


def _verdict_for(decisions: int, agreement: float | None, meets_bar: bool) -> str:
    """One word for how a candidate rule scored, in the service's own vocabulary."""
    if decisions < assumptions.MINIMUM_DECISIONS_FOR_A_GATE:
        return "too_few_decisions"
    if meets_bar:
        return "meets_bar"
    if agreement is None:
        return "too_few_decisions"
    return "below_agreement"


def _gates(performance: Performance) -> Panel[GateTable]:
    """Every candidate rule, scored on coverage and agreement, and never on anything else."""
    if performance.totals.investigation.decisions == 0:
        return Panel(
            empty_reason=(
                "No products were investigated during this period, so potential automation "
                "rules cannot be evaluated."
            ),
            data=None,
        )
    return Panel(
        empty_reason=None,
        data=GateTable(
            title="Potential automation rules",
            columns=(
                "Order value",
                "AI confidence",
                "Decisions reviewed",
                "Share of investigated work",
                "Accepted without changes",
                "Evaluation",
            ),
            rows=tuple(
                GateRow(
                    value_band=gate.value_band,
                    confidence_band=gate.confidence_band,
                    decisions_text=_count_text(gate.decisions),
                    coverage_text=_percent_text(gate.coverage),
                    agreement_text=_percent_text(gate.agreement),
                    verdict=_verdict_for(gate.decisions, gate.agreement, gate.meets_bar),
                )
                for gate in performance.gates
            ),
            caveat=assumptions.GATE_BAR_DESCRIPTION,
        ),
    )


def _figures(performance: Performance) -> tuple[Figure, ...]:
    """The tiles across the top, in the order a reader should meet them."""
    overall = performance.totals.overall
    investigated = performance.totals.investigation
    return (
        Figure(
            label="Total decisions reviewed",
            value=_count_text(overall.decisions),
            note="Includes AI-investigated products and claims stopped by eligibility checks.",
        ),
        Figure(
            label="Required changes or reinvestigation",
            value=_percent_text(share(investigated.interventions, investigated.decisions)),
            note=(
                "Share of AI-investigated products where a representative changed the outcome, "
                "reimbursement, or email wording, or sent the case back."
            ),
        ),
        Figure(
            label="Reimbursement amount changed",
            value=_percent_text(share(investigated.amount_changes, investigated.decisions)),
            note=(
                "Share of AI-investigated products where a representative changed the "
                "recommended reimbursement amount."
            ),
        ),
        Figure(
            label="Sent back for reinvestigation",
            value=_percent_text(share(investigated.sent_back, investigated.decisions)),
            note="Share of AI-investigated products returned with feedback for another run.",
        ),
        Figure(
            label="Average review time",
            value=_minutes_text(overall.average_rep_minutes),
            note="Average representative review time per decision.",
        ),
    )


def _savings(performance: Performance) -> tuple[Figure, ...]:
    """What the time saved is worth, and what was paid for it."""
    savings = performance.savings
    return (
        Figure(
            label="Estimated representative time saved",
            value=_hours_text(savings.rep_hours_saved),
            note="Compared with the assumed time needed to handle the same work without AI.",
        ),
        Figure(
            label="Estimated value of time saved",
            value=_money_text(savings.gross_saving_usd),
            note="Estimated time saved multiplied by the assumed representative hourly cost.",
        ),
        Figure(
            label="Estimated AI investigation cost",
            value=_money_text(savings.ai_cost_usd),
            note=(
                "Estimated AI model and image-processing costs. Excludes claim reimbursements "
                "and representative time."
            ),
        ),
        Figure(
            label="Estimated net savings",
            value=_money_text(savings.net_saving_usd),
            note=(
                "Estimated value of time saved minus estimated AI investigation costs. Excludes "
                "claim reimbursements and other operating costs."
            ),
        ),
    )


def _assumptions() -> tuple[Assumption, ...]:
    """The numbers behind the money, each with the service's own explanation."""
    return (
        Assumption(
            label="Assumed representative hourly cost",
            value=_money_text(assumptions.REP_HOURLY_RATE_USD),
            description=assumptions.REP_HOURLY_RATE_DESCRIPTION,
            marker="PROVISIONAL",
        ),
        Assumption(
            label="Estimated AI cost per investigated product",
            value=_money_text(assumptions.AI_COST_PER_CLAIM_USD),
            description=assumptions.AI_COST_PER_CLAIM_DESCRIPTION,
            marker="PROVISIONAL",
        ),
        Assumption(
            label="Assumed manual time per investigated product",
            value=f"{assumptions.MANUAL_MINUTES_PER_INVESTIGATION} min",
            description=assumptions.MANUAL_MINUTES_PER_INVESTIGATION_DESCRIPTION,
            marker="PROVISIONAL",
        ),
        Assumption(
            label="Assumed manual time per stopped claim",
            value=f"{assumptions.MANUAL_MINUTES_PER_SCREENING} min",
            description=assumptions.MANUAL_MINUTES_PER_SCREENING_DESCRIPTION,
            marker="PROVISIONAL",
        ),
    )


def build(performance: Performance, period: str, generated_at: datetime) -> AnalysisView:
    """Turn the worked-out figures into everything the screen draws.

    Args:
        performance: The counts and rates, already worked out.
        period: Which stretch of time was asked for, so the screen can show it as chosen.
        generated_at: When this was put together, shown so a reader knows how fresh it is.

    Returns:
        Every tile, chart, table and sentence, with each number carried both as a value to draw
        and as the words to read.
    """
    investigated = performance.totals.investigation
    return AnalysisView(
        period_label=(
            f"Data period: {_day_text(performance.starts_at)} through "
            f"{_day_text(performance.ends_at)}."
        ),
        starts_at=performance.starts_at,
        ends_at=performance.ends_at,
        presets=_presets(resolve_period(period)),
        hero=Figure(
            label="AI recommendations accepted without changes",
            value=_percent_text(share(investigated.direct_approvals, investigated.decisions)),
            note=(
                "Share of AI-investigated products where the representative kept the recommended "
                "outcome, reimbursement amount, and merchant email unchanged."
            ),
        ),
        figures=_figures(performance),
        savings=_savings(performance),
        assumptions=_assumptions(),
        approval_trend=_approval_trend(performance),
        intervention_mix=_intervention_mix(performance),
        calibration=_calibration(performance),
        readiness=_readiness(performance),
        disagreement=_disagreement(performance),
        review_time=_review_time(performance),
        gates=_gates(performance),
        generated_at=generated_at,
    )
