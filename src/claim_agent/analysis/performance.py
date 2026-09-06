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


GATE_CONFIDENCE_BANDS = tuple(name for name, _low, _high in CONFIDENCE_BANDS[1:])


def share(part: int, whole: int) -> float | None:
    """What fraction of `whole` is `part`, or `None` when there is nothing to divide."""
    if whole == 0:
        return None
    return part / whole


def band_for(value: float, bands: Sequence[tuple[str, float, float]]) -> str | None:
    """Which band a figure falls in, or `None` if it falls outside all of them."""
    for position, (name, low, high) in enumerate(bands):
        is_last = position == len(bands) - 1
        if low <= value < high or (is_last and value == high):
            return name
    return None


def value_band_for(amount: Decimal | None) -> str | None:
    """Which order-value band a claim falls in, or `None` when the order could not be read."""
    if amount is None:
        return None
    for name, low, high in VALUE_BANDS:
        if (low is None or amount >= low) and (high is None or amount < high):
            return name
    return None


class Tally(BaseModel):
    """How many decisions of one kind there were, and how they broke down."""

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
    """Count a group of decisions."""
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
    """How often people agreed, among decisions the system said it was this sure about."""

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
    """One way of cutting the claims up, and what each part of it looks like."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    segments: tuple[Segment, ...]

    @property
    def spread(self) -> float | None:
        """How far apart the readiest and least ready parts are, or nothing to compare."""
        rates = [segment.readiness for segment in self.segments if segment.readiness is not None]
        if len(rates) < 2:
            return None
        return max(rates) - min(rates)


class GateScore(BaseModel):
    """One candidate rule, scored on how much it would cover and how often people agreed."""

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
    """What the time saved is worth, and what it cost to save it."""

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
    """The midnight beginning the Monday of this moment's week, in UTC."""
    at_utc = moment.astimezone(UTC)
    midnight = at_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def _weeks_between(starts_at: datetime, ends_at: datetime) -> list[datetime]:
    """Every week start from `starts_at` up to but not including `ends_at`."""
    weeks: list[datetime] = []
    cursor = week_starting(starts_at)
    while cursor < ends_at:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def _median_minutes(decisions: Sequence[DecisionRecord]) -> float | None:
    """The middle review time, or `None` when nobody reviewed anything."""
    if not decisions:
        return None
    return median(decision.rep_minutes for decision in decisions)


def _confidence_bands(decisions: Sequence[DecisionRecord]) -> tuple[ConfidenceBandStats, ...]:
    """Group investigated decisions by how sure the system said it was, and count agreement."""
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
    """Count disagreement against each of the next actions that can be proposed."""
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
    """Cut the claims by one property, readiest part first."""
    parts: dict[str, list[DecisionRecord]] = {}
    for decision in investigated:
        value = of(decision)
        if value is not None:
            parts.setdefault(value, []).append(decision)
    counted = [_segment(key, rows) for key, rows in parts.items()]
    counted.sort(key=lambda one: (-(one.readiness or 0.0), -one.decisions, one.name))
    return SegmentGroup(name=name, segments=tuple(counted))


def _readiness(investigated: Sequence[DecisionRecord]) -> tuple[SegmentGroup, ...]:
    """Cut the investigated claims four ways, and count how ready each part came back."""
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
    """Score every candidate rule: an order-value band crossed with a confidence band."""
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
    """Turn minutes saved into money, and take off what the AI cost."""
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
    """Work out every figure the analysis screen shows, for one stretch of time."""
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
