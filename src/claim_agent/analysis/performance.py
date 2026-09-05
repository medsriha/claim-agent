"""Counting what representatives decided, and working out what it adds up to.

This is the arithmetic behind the analysis screen and it is the only place any of it happens.
Nothing here reads a database, calls anything, or asks a model: it takes decisions that were
already made and returns figures. That is what makes every number on the screen checkable by a
test with no network, no database and no AI in it.

**Two populations, never added together.** A claim the quick checks stopped and a claim that was
investigated are counted apart everywhere, because they are different arguments about
automation. A stopped claim costs nothing to decide and people almost always agree with it;
folding it into one figure would make the advice look better than it is.

**"Agreement" is not "accuracy".** Nothing here knows what the right answer was. It knows what a
person chose. Calling that accuracy would be asserting the person is always right, which nobody
has established, so the word is not used.

**A rate over nothing is `None`, never zero.** A week in which nobody decided anything has no
direct-approval rate. Reporting it as 0% would draw a line to the floor and read as a collapse in
quality, when the truth is that there is nothing to report.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from pydantic import BaseModel, ConfigDict

from claim_agent.analysis.assumptions import (
    AI_COST_PER_CLAIM_USD,
    CONFIDENCE_BANDS,
    MANUAL_MINUTES_PER_INVESTIGATION,
    MANUAL_MINUTES_PER_SCREENING,
    MINIMUM_AGREEMENT_FOR_A_GATE,
    MINIMUM_DECISIONS_FOR_A_GATE,
    REP_HOURLY_RATE_USD,
    VALUE_BANDS,
)
from claim_agent.domain.decision import DecisionRecord, DecisionStage, RepAction
from claim_agent.domain.outcome import Recommendation

CENTS = Decimal("0.01")
"""Money is rounded to whole cents, the same way a reimbursement is."""

MINUTES_IN_AN_HOUR = Decimal("60")

# The confidence bands a candidate gate may be built on. The lowest band is left out because the
# system already refuses to recommend paying there (FR-1.15) — a rule that let claims through
# below the level at which the rules withhold payment would be arguing with itself.
GATE_CONFIDENCE_BANDS = tuple(name for name, _low, _high in CONFIDENCE_BANDS[1:])


def share(part: int, whole: int) -> float | None:
    """What fraction of `whole` is `part`, or `None` when there is nothing to divide.

    Returning `None` rather than zero is the point of this function. Nought out of nought is not
    nought per cent; it is a question with no answer, and every chart and tile downstream draws a
    gap for it rather than a value.
    """
    if whole == 0:
        return None
    return part / whole


def band_for(value: float, bands: Sequence[tuple[str, float, float]]) -> str | None:
    """Which band a figure falls in, or `None` if it falls outside all of them.

    The upper edge of a band is excluded so that neighbouring bands cannot both claim a figure —
    except on the last band, where it is included, so that something the system was completely
    sure of still has somewhere to go.
    """
    for position, (name, low, high) in enumerate(bands):
        is_last = position == len(bands) - 1
        if low <= value < high or (is_last and value == high):
            return name
    return None


def value_band_for(amount: Decimal | None) -> str | None:
    """Which order-value band a claim falls in, or `None` when the order could not be read.

    An order whose value is unknown is left out of the value bands rather than guessed into the
    cheapest one. It is not the same as an order worth nothing.
    """
    if amount is None:
        return None
    for name, low, high in VALUE_BANDS:
        if (low is None or amount >= low) and (high is None or amount < high):
            return name
    return None


class Tally(BaseModel):
    """How many decisions of one kind there were, and how they broke down.

    Counts only. Every rate is worked out from these by the caller, so that a rate over nothing
    can be reported as nothing rather than as zero.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decisions: int = 0
    direct_approvals: int = 0
    wording_only: int = 0
    substance_changed: int = 0
    sent_back: int = 0
    outcome_changes: int = 0
    amount_changes: int = 0
    agreed: int = 0
    rep_minutes: int = 0
    manual_minutes: int = 0

    @property
    def interventions(self) -> int:
        """Decisions that took a person's attention beyond reading and accepting."""
        return self.decisions - self.direct_approvals

    @property
    def average_rep_minutes(self) -> float | None:
        """Average representative review time, or no figure when there were no decisions."""
        if self.decisions == 0:
            return None
        return self.rep_minutes / self.decisions


def _manual_minutes_for(stage: DecisionStage) -> int:
    """How long this kind of decision is taken to need without the system helping."""
    if stage is DecisionStage.SCREENING:
        return MANUAL_MINUTES_PER_SCREENING
    return MANUAL_MINUTES_PER_INVESTIGATION


def tally_of(decisions: Iterable[DecisionRecord]) -> Tally:
    """Count a group of decisions.

    The four ways a decision can go are counted so that they add up to the total exactly once
    each: taken as it stood, taken after only the wording changed, taken after the outcome or the
    amount changed, or sent back. A stacked chart of those four is only honest if nothing can
    land in two of them, which is why they are decided here in one place rather than by four
    separate filters.
    """
    counts = {
        "decisions": 0,
        "direct_approvals": 0,
        "wording_only": 0,
        "substance_changed": 0,
        "sent_back": 0,
        "outcome_changes": 0,
        "amount_changes": 0,
        "agreed": 0,
        "rep_minutes": 0,
        "manual_minutes": 0,
    }
    for decision in decisions:
        counts["decisions"] += 1
        counts["rep_minutes"] += decision.rep_minutes
        counts["manual_minutes"] += _manual_minutes_for(decision.stage)
        if decision.outcome_changed:
            counts["outcome_changes"] += 1
        if decision.amount_changed:
            counts["amount_changes"] += 1
        if decision.agreed_with_recommendation:
            counts["agreed"] += 1

        if decision.action is RepAction.SENT_BACK:
            counts["sent_back"] += 1
        elif decision.outcome_changed or decision.amount_changed:
            counts["substance_changed"] += 1
        elif decision.email_edited:
            counts["wording_only"] += 1
        else:
            counts["direct_approvals"] += 1
    return Tally(**counts)


class StageTallies(BaseModel):
    """The same counts kept three ways: everything, and each population on its own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: Tally
    screening: Tally
    investigation: Tally


def _tallies_for(decisions: Sequence[DecisionRecord]) -> StageTallies:
    """Count a group of decisions once altogether and once per population."""
    return StageTallies(
        overall=tally_of(decisions),
        screening=tally_of(d for d in decisions if d.stage is DecisionStage.SCREENING),
        investigation=tally_of(d for d in decisions if d.stage is DecisionStage.INVESTIGATION),
    )


class Week(BaseModel):
    """One week of decisions, named by the moment it starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    starts_at: datetime
    tallies: StageTallies
    median_rep_minutes: float | None


class ConfidenceBandStats(BaseModel):
    """How often people agreed, among decisions the system said it was this sure about.

    This is the comparison the whole screen exists for. `stated_low` and `stated_high` are what
    the system claimed; `agreed` out of `decisions` is what actually happened. Nothing in this
    project has ever put those two numbers side by side before.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    stated_low: float
    stated_high: float
    decisions: int
    agreed: int

    @property
    def agreement(self) -> float | None:
        """How often a representative accepted the advice in this band."""
        return share(self.agreed, self.decisions)


class OutcomeStats(BaseModel):
    """How often people disagreed with one of the three proposed actions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation
    decisions: int
    disagreed: int

    @property
    def disagreement(self) -> float | None:
        """How often a representative changed or rejected this recommendation."""
        return share(self.disagreed, self.decisions)


class Segment(BaseModel):
    """One kind of claim, and how often it went out exactly as the system produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    decisions: int
    direct_approvals: int

    @property
    def readiness(self) -> float | None:
        """The share of this kind that needed nothing doing to it."""
        return share(self.direct_approvals, self.decisions)


class SegmentGroup(BaseModel):
    """One way of cutting the claims up, and what each part of it looks like.

    Three cuts are reported, and they answer the same question three ways: *which claims come back
    ready, and which need work?* Grouping by what the system recommended says whether some kinds
    of answer are harder to get right than others; by what the order was worth says whether
    expensive claims are harder; by how sure the system said it was says whether it knows in
    advance which is which.

    Every part is reported even when nothing fell into it, so a reader sees an untested corner
    rather than inferring it from a missing row.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    segments: tuple[Segment, ...]

    @property
    def spread(self) -> float | None:
        """How far apart the readiest and least ready parts are, or nothing to compare.

        This is the number that says whether a cut is worth anything. A group whose parts all
        come back ready about as often tells nobody which claims to expect trouble from; one that
        spreads widely is a way of sorting the work before anybody starts on it. Reporting it
        means a flat group reads as a finding rather than as bars somebody has to eyeball.
        """
        rates = [segment.readiness for segment in self.segments if segment.readiness is not None]
        if len(rates) < 2:
            return None
        return max(rates) - min(rates)


class GateScore(BaseModel):
    """One candidate rule, scored on how much it would cover and how often people agreed.

    **Scored, never chosen, and never switched on.** FR-2.9 says a report leaves review in
    exactly one way — a person approving it — and that no confidence level changes that. FR-3.1
    calls the same thing a hard invariant. `meets_bar` says a rule cleared a bar we invented; it
    does not say anybody may act on it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value_band: str
    confidence_band: str
    decisions: int
    agreed: int
    coverage: float | None
    meets_bar: bool

    @property
    def agreement(self) -> float | None:
        """How often a representative accepted the advice inside this rule."""
        return share(self.agreed, self.decisions)


class Savings(BaseModel):
    """What the time saved is worth, and what it cost to save it.

    Every figure is money and every figure is a `Decimal`. The hours behind them are whole
    minutes divided by sixty, so nothing here has ever been a floating-point number.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rep_hours_saved: Decimal
    gross_saving_usd: Decimal
    ai_cost_usd: Decimal
    net_saving_usd: Decimal


class Performance(BaseModel):
    """Everything the analysis screen is drawn from, for one stretch of time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    starts_at: datetime
    ends_at: datetime
    totals: StageTallies
    weeks: tuple[Week, ...]
    confidence_bands: tuple[ConfidenceBandStats, ...]
    outcomes: tuple[OutcomeStats, ...]
    readiness: tuple[SegmentGroup, ...]
    gates: tuple[GateScore, ...]
    savings: Savings
    median_rep_minutes: float | None


def week_starting(moment: datetime) -> datetime:
    """The midnight beginning the Monday of this moment's week, in UTC.

    Weeks start on Monday because that is what a business week means to the people reading this,
    and they are cut in UTC because every other time in this system is. A machine in another
    timezone therefore buckets a decision exactly the same way, which is what stops the same data
    producing two different charts (NFR-1).
    """
    at_utc = moment.astimezone(UTC)
    midnight = at_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def _weeks_between(starts_at: datetime, ends_at: datetime) -> list[datetime]:
    """Every week start from `starts_at` up to but not including `ends_at`.

    Built from the calendar rather than from the decisions, so a week nobody decided anything in
    still appears — as a gap. Leaving it out would quietly close the space and make a quiet
    fortnight look like a busy one.
    """
    weeks: list[datetime] = []
    cursor = week_starting(starts_at)
    while cursor < ends_at:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def _median_minutes(decisions: Sequence[DecisionRecord]) -> float | None:
    """The middle review time, or `None` when nobody reviewed anything.

    The middle rather than the average: one claim that sat in somebody's queue over a weekend
    would drag an average somewhere no real review ever was.
    """
    if not decisions:
        return None
    return median(decision.rep_minutes for decision in decisions)


def _confidence_bands(decisions: Sequence[DecisionRecord]) -> tuple[ConfidenceBandStats, ...]:
    """Group investigated decisions by how sure the system said it was, and count agreement.

    Decisions with no stated confidence are left out rather than counted as unsure. A screening
    decision has no confidence because nothing was asked of the AI, and putting it in the bottom
    band would invent an opinion nobody offered.
    """
    per_band: dict[str, list[DecisionRecord]] = {name: [] for name, _low, _high in CONFIDENCE_BANDS}
    for decision in decisions:
        if decision.stated_confidence is None:
            continue
        name = band_for(decision.stated_confidence, CONFIDENCE_BANDS)
        if name is not None:
            per_band[name].append(decision)

    return tuple(
        ConfidenceBandStats(
            name=name,
            stated_low=low,
            stated_high=high,
            decisions=len(per_band[name]),
            agreed=sum(1 for d in per_band[name] if d.agreed_with_recommendation),
        )
        for name, low, high in CONFIDENCE_BANDS
    )


def _outcomes(decisions: Sequence[DecisionRecord]) -> tuple[OutcomeStats, ...]:
    """Count disagreement against each of the three proposed actions.

    All four are always reported, including any nobody recommended, so a reader sees what did not
    happen rather than inferring it from a missing row.
    """
    stats: list[OutcomeStats] = []
    for outcome in Recommendation:
        matching = [d for d in decisions if d.recommended.outcome is outcome]
        stats.append(
            OutcomeStats(
                outcome=outcome,
                decisions=len(matching),
                disagreed=sum(1 for d in matching if not d.agreed_with_recommendation),
            )
        )
    return tuple(stats)


def _segment(name: str, decisions: Sequence[DecisionRecord]) -> Segment:
    """Count one kind of claim."""
    return Segment(
        name=name,
        decisions=len(decisions),
        direct_approvals=sum(1 for one in decisions if one.is_direct_approval),
    )


def _by(
    name: str,
    investigated: Sequence[DecisionRecord],
    of: Callable[[DecisionRecord], str | None],
) -> SegmentGroup:
    """Cut the claims by one property, readiest part first.

    Ordered by how ready each part came back rather than by name or by size, so the group reads
    as a run from the claims that look after themselves down to the ones that do not. That is the
    only thing anybody is trying to see here, and leaving it to be eyeballed off unordered bars is
    what makes a chart like this hard to read. How many claims each part holds is printed beside
    it, so a small part cannot pass itself off as an important one.

    These properties have no natural order of their own — one carrier is not "more" than another —
    which is what makes sorting them by the measure the right thing to do. A property that *is*
    ordered, such as how sure the system said it was, keeps its own order instead.

    Claims the property is unknown for are left out rather than gathered into a part of their own,
    which would be a group named after a gap in the data.
    """
    parts: dict[str, list[DecisionRecord]] = {}
    for decision in investigated:
        value = of(decision)
        if value is not None:
            parts.setdefault(value, []).append(decision)
    counted = [_segment(key, rows) for key, rows in parts.items()]
    counted.sort(key=lambda one: (-(one.readiness or 0.0), -one.decisions, one.name))
    return SegmentGroup(name=name, segments=tuple(counted))


def _readiness(investigated: Sequence[DecisionRecord]) -> tuple[SegmentGroup, ...]:
    """Cut the investigated claims four ways, and count how ready each part came back.

    **Three of the four are known before anybody looks at the claim** — what the merchant said
    was damaged, what they said caused it, and who carried the parcel. That is deliberate: a cut
    by something the investigation produced, such as what it ended up recommending, can only
    describe work already done. These say something about work about to arrive.

    The fourth, how sure the system said it was, is the investigation's own opinion. It is here
    because it is the strongest signal there is, and because comparing it with the other three is
    the whole question — if it tracks them, it is reading the claim; if it beats them, it is
    seeing something they do not.

    Only investigated claims, deliberately. A claim the quick checks stopped is decided by fixed
    rules and almost always accepted, so folding those in would put a large, easy population into
    every cut and flatten the differences this is meant to show.
    """
    return (
        _by("What the merchant reported", investigated, lambda one: one.defect_type),
        _by("What they said caused it", investigated, lambda one: one.damage_type),
        _by("Who carried the parcel", investigated, lambda one: one.carrier),
        SegmentGroup(
            name="How sure the system said it was",
            segments=tuple(
                _segment(
                    band_name,
                    [
                        one
                        for one in investigated
                        if one.stated_confidence is not None
                        and band_for(one.stated_confidence, CONFIDENCE_BANDS) == band_name
                    ],
                )
                for band_name, _low, _high in CONFIDENCE_BANDS
            ),
        ),
    )


def _gates(investigated: Sequence[DecisionRecord]) -> tuple[GateScore, ...]:
    """Score every candidate rule: an order-value band crossed with a confidence band.

    Coverage is measured against every investigated decision, including those whose order value
    could not be read, because coverage answers "how much of the work would this rule take on"
    and work nobody could price is still work.
    """
    total = len(investigated)
    scores: list[GateScore] = []
    for value_name, _low, _high in VALUE_BANDS:
        for confidence_name in GATE_CONFIDENCE_BANDS:
            inside = [
                d
                for d in investigated
                if value_band_for(d.order_value_usd) == value_name
                and d.stated_confidence is not None
                and band_for(d.stated_confidence, CONFIDENCE_BANDS) == confidence_name
            ]
            agreed = sum(1 for d in inside if d.agreed_with_recommendation)
            agreement = share(agreed, len(inside))
            scores.append(
                GateScore(
                    value_band=value_name,
                    confidence_band=confidence_name,
                    decisions=len(inside),
                    agreed=agreed,
                    coverage=share(len(inside), total),
                    meets_bar=(
                        len(inside) >= MINIMUM_DECISIONS_FOR_A_GATE
                        and agreement is not None
                        and agreement >= MINIMUM_AGREEMENT_FOR_A_GATE
                    ),
                )
            )
    return tuple(scores)


def _savings(totals: StageTallies) -> Savings:
    """Turn minutes saved into money, and take off what the AI cost.

    The arithmetic is deliberately dull and entirely in `Decimal`: minutes saved, divided by
    sixty, multiplied by an hourly rate, less a cost for each claim the AI actually investigated.
    A claim the quick checks stopped is charged nothing, because no AI was asked about it.

    Both the rate and the per-claim cost are figures we chose. They travel to the screen with
    their own explanation so that a reader can see what the total rests on.
    """
    minutes_saved = totals.overall.manual_minutes - totals.overall.rep_minutes
    hours_saved = (Decimal(minutes_saved) / MINUTES_IN_AN_HOUR).quantize(CENTS, ROUND_HALF_UP)
    gross = (hours_saved * REP_HOURLY_RATE_USD).quantize(CENTS, ROUND_HALF_UP)
    ai_cost = (Decimal(totals.investigation.decisions) * AI_COST_PER_CLAIM_USD).quantize(
        CENTS, ROUND_HALF_UP
    )
    return Savings(
        rep_hours_saved=hours_saved,
        gross_saving_usd=gross,
        ai_cost_usd=ai_cost,
        net_saving_usd=(gross - ai_cost).quantize(CENTS, ROUND_HALF_UP),
    )


def summarise(
    decisions: Sequence[DecisionRecord], starts_at: datetime, ends_at: datetime
) -> Performance:
    """Work out every figure the analysis screen shows, for one stretch of time.

    Args:
        decisions: Every decision taken in the window, in any order. Decisions outside the window
            are ignored rather than rejected, so a caller that reads a little too widely still
            gets a correct answer.
        starts_at: The first moment the window covers, in UTC.
        ends_at: The first moment it does not, in UTC.

    Returns:
        The counts, the weekly series, the confidence comparison, the candidate rules and the
        savings. Everything is present even when nothing was decided: the weeks come from the
        calendar and the bands and outcomes from their own definitions, so an empty period is an
        empty chart rather than a missing one.
    """
    inside = [d for d in decisions if starts_at <= d.decided_at < ends_at]
    by_week: dict[datetime, list[DecisionRecord]] = {}
    for decision in inside:
        by_week.setdefault(week_starting(decision.decided_at), []).append(decision)

    weeks = tuple(
        Week(
            starts_at=start,
            tallies=_tallies_for(by_week.get(start, [])),
            median_rep_minutes=_median_minutes(by_week.get(start, [])),
        )
        for start in _weeks_between(starts_at, ends_at)
    )
    investigated = [d for d in inside if d.stage is DecisionStage.INVESTIGATION]
    totals = _tallies_for(inside)
    return Performance(
        starts_at=starts_at,
        ends_at=ends_at,
        totals=totals,
        weeks=weeks,
        confidence_bands=_confidence_bands(investigated),
        outcomes=_outcomes(investigated),
        readiness=_readiness(investigated),
        gates=_gates(investigated),
        savings=_savings(totals),
        median_rep_minutes=_median_minutes(inside),
    )
