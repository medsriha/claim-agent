from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import UtcDatetime

Drawn = TypeVar("Drawn")


class Point(BaseModel):
    """One value on a chart: where to draw it, and what it says."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | None
    text: str
    label: str


class Gridline(BaseModel):
    """One horizontal rule across a chart, and the words at the end of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    at: float
    label: str


class Domain(BaseModel):
    """Where a chart's up-and-down axis begins and ends."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum: float
    maximum: float


class Series(BaseModel):
    """One line on a chart, and the sentence that describes it when nothing is picked out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    points: tuple[Point, ...]


class TimeChart(BaseModel):
    """Something plotted week by week."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    y_label: str
    domain: Domain
    gridlines: tuple[Gridline, ...]
    ticks: tuple[int, ...]
    series: tuple[Series, ...]
    summary: str


class BandPoint(BaseModel):
    """One week of one band of a stacked chart."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    upper: float | None
    text: str
    label: str


class Band(BaseModel):
    """One band of a stacked chart, from the bottom up."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    points: tuple[BandPoint, ...]


class StackedChart(BaseModel):
    """How a whole was divided up, week by week."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    y_label: str
    domain: Domain
    gridlines: tuple[Gridline, ...]
    ticks: tuple[int, ...]
    bands: tuple[Band, ...]
    summary: str


class CalibrationBand(BaseModel):
    """What the system claimed about one band, and what actually happened in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    band: str
    stated_low: float
    stated_high: float
    agreement: Point
    volume: Point


class Calibration(BaseModel):
    """The comparison between how sure the system said it was and how often it was accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    bands: tuple[CalibrationBand, ...]
    domain: Domain
    gridlines: tuple[Gridline, ...]
    volume_domain: Domain
    summary: str


class BarChart(BaseModel):
    """A handful of named things, each with one figure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    domain: Domain
    gridlines: tuple[Gridline, ...]
    bars: tuple[Point, ...]
    summary: str


class ReadinessRow(BaseModel):
    """One kind of claim: how often it came back ready, and how much of the work it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    ready: Point
    volume: Point


class ReadinessGroup(BaseModel):
    """One way of cutting the claims up, with each part of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    spread_text: str
    rows: tuple[ReadinessRow, ...]


class Readiness(BaseModel):
    """Which kinds of claim come back ready to send, and which need a person."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    groups: tuple[ReadinessGroup, ...]
    domain: Domain
    summary: str


class GateRow(BaseModel):
    """One candidate rule, scored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value_band: str
    confidence_band: str
    decisions_text: str
    coverage_text: str
    agreement_text: str
    verdict: str


class GateTable(BaseModel):
    """Every candidate rule, in the order the service scored them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    columns: tuple[str, ...]
    rows: tuple[GateRow, ...]
    caveat: str


class Figure(BaseModel):
    """One tile: a label, a figure already written out, and an optional line under it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    value: str
    note: str | None


class Assumption(BaseModel):
    """One number the reporting rests on that nobody has confirmed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    value: str
    description: str
    marker: str


class Preset(BaseModel):
    """One stretch of time the screen can ask for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    applied: bool


class Panel(BaseModel, Generic[Drawn]):
    """One part of the screen, which may have nothing to show."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    empty_reason: str | None
    data: Drawn | None


class AnalysisView(BaseModel):
    """Everything the analysis screen draws."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    period_label: str
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    presets: tuple[Preset, ...]
    hero: Figure
    figures: tuple[Figure, ...]
    savings: tuple[Figure, ...]
    assumptions: tuple[Assumption, ...]
    approval_trend: Panel[TimeChart]
    intervention_mix: Panel[StackedChart]
    calibration: Panel[Calibration]
    readiness: Panel[Readiness]
    disagreement: Panel[BarChart]
    review_time: Panel[TimeChart]
    gates: Panel[GateTable]
    generated_at: UtcDatetime
