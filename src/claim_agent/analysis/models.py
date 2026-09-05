from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import UtcDatetime

Drawn = TypeVar("Drawn")


class Point(BaseModel):
    """One value on a chart: where to draw it, and what it says.

    `value` exists only to become a coordinate. `text` is the figure a person reads, already
    written out. `label` names the position — a week, a band, an outcome.

    `value` is `None` when there is nothing to draw. The screen leaves a gap.
    """

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
    """Where a chart's up-and-down axis begins and ends.

    Sent rather than worked out in the browser, because where an axis stops is a judgement about
    the measure. An axis that begins at forty per cent makes a small change look enormous, and
    that decision belongs with the people who understand the number.
    """

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
    """One week of one band of a stacked chart.

    `upper` is the **cumulative** top edge of this band, counting every band below it — already
    added up here. The browser draws a shape between one band's edge and the next and never adds
    anything together, which is what stops four shares that must total one from drifting apart by
    a pixel.

    `label` names the week, so the screen can say which one is picked out without working it out
    from a position in a list.
    """

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
    """What the system claimed about one band, and what actually happened in it.

    `band` names the range in words — "85 to 95% sure" — and `stated_low` and `stated_high` are
    the same range as numbers, for drawing the shaded box behind the bar. There is no third field
    repeating it as prose: the band's own name already says what the system claimed, and two
    fields saying the same thing is two chances to disagree.

    `agreement` is how often a representative then accepted the advice. Whether it lands inside
    the claimed range is the whole question, and it is left to the reader to see rather than
    worked out here — the difference between the two is not sent, because a difference is a
    subtraction and this screen does not tell people what to conclude.
    """

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
    """One kind of claim: how often it came back ready, and how much of the work it is.

    `ready` is the share that went out exactly as produced — same outcome, same amount, not a word
    of the email rewritten. `volume` is how many decisions that share was worked out from, so a
    reader can tell a real pattern from three claims that happened to agree.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    ready: Point
    volume: Point


class ReadinessGroup(BaseModel):
    """One way of cutting the claims up, with each part of it.

    `spread_text` says how far apart the readiest and least ready parts are, which is the whole
    measure of whether this cut is worth anything: a group whose parts all come back ready about
    as often cannot tell anybody which claims to expect trouble from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    spread_text: str
    rows: tuple[ReadinessRow, ...]


class Readiness(BaseModel):
    """Which kinds of claim come back ready to send, and which need a person.

    Three cuts of the same claims, answering the same question three ways. The point is not any
    one number but the spread: if some kinds come back ready far more often than others, the work
    can be told apart in advance, which is the thing worth knowing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    groups: tuple[ReadinessGroup, ...]
    domain: Domain
    summary: str


class GateRow(BaseModel):
    """One candidate rule, scored.

    `verdict` is the service's own word — `meets_bar`, `below_agreement`, `too_few_decisions` —
    reshaped to read on screen rather than replaced with wording of the screen's own.

    Meeting the bar is not permission. FR-2.9 says a person approving is the only way a claim
    leaves review, and FR-3.1 calls that a hard invariant, so nothing here is a setting and there
    is deliberately nothing beside these rows to switch on.
    """

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
    """One number the reporting rests on that nobody has confirmed.

    Shown beside the figures it produces, with the service's own explanation and its own mark
    saying it is provisional — the same arrangement the rules screen uses, so a reader can see
    what a total is built on instead of taking it on trust.
    """

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
    """One part of the screen, which may have nothing to show.

    `data` is absent exactly when `empty_reason` is present. The reason is a sentence, because
    an empty box reads as a screen that broke and the service is the only thing that knows why
    there is nothing there.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    empty_reason: str | None
    data: Drawn | None


class AnalysisView(BaseModel):
    """Everything the analysis screen draws.

    The tiles, the savings and the assumptions are ordered lists the screen renders without
    knowing what is in them, so another figure can be added here and appear on screen without the
    screen being touched — the same arrangement that lets a new rule appear on the admin panel.
    """

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
