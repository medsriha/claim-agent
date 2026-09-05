/**
 * The shapes the analysis screen is sent.
 *
 * These mirror `src/claim_agent/analysis/models.py` field for field. One thing about them is
 * worth understanding before reading any of the chart code: **every figure arrives twice.**
 * A point carries `value`, which exists only to become a position on the screen, and `text`,
 * which is the figure already written out for a person to read.
 *
 * That is what lets this screen keep the rule the rest of the project keeps — the browser works
 * nothing out. It never divides to make a percentage, never adds a column up, never decides
 * where an axis should stop, and never turns an amount of money into a number. It turns a value
 * into a length, and that is all.
 *
 * A `value` of `null` means there is nothing to draw: a week nobody decided anything in. It is
 * not zero, and a chart must leave a gap rather than drop a line to the floor.
 */

/** One value on a chart: where to draw it, what it says, and what position it belongs to. */
export interface Point {
  readonly value: number | null;
  readonly text: string;
  readonly label: string;
}

/** One horizontal rule across a chart, and the words at the end of it. */
export interface Gridline {
  readonly at: number;
  readonly label: string;
}

/** Where a chart's up-and-down axis begins and ends. Decided by the service, never here. */
export interface Domain {
  readonly minimum: number;
  readonly maximum: number;
}

/** One line on a chart. */
export interface Series {
  readonly name: string;
  readonly points: readonly Point[];
}

/** Something plotted week by week. */
export interface TimeChart {
  readonly title: string;
  readonly y_label: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly ticks: readonly number[];
  readonly series: readonly Series[];
  readonly summary: string;
}

/**
 * One week of one band of a stacked chart.
 *
 * `upper` is the band's **cumulative** top edge, counting every band below it — already added up
 * by the service. Drawing a band means filling between this edge and the one below, so nothing
 * here ever adds two shares together.
 *
 * `label` names the week, so the screen never has to work out which one a position is.
 */
export interface BandPoint {
  readonly upper: number | null;
  readonly text: string;
  readonly label: string;
}

/** One band of a stacked chart, from the bottom up. */
export interface Band {
  readonly name: string;
  readonly points: readonly BandPoint[];
}

/** How a whole was divided up, week by week. */
export interface StackedChart {
  readonly title: string;
  readonly y_label: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly ticks: readonly number[];
  readonly bands: readonly Band[];
  readonly summary: string;
}

/**
 * What the system claimed about one band, and what actually happened in it.
 *
 * The difference between the two is deliberately not sent. Whether the measured bar lands inside
 * the claimed band is for a reader to see, and a subtraction is not this screen's to do.
 *
 * `band` names the range in words; `stated_low` and `stated_high` are the same range as numbers,
 * for drawing the shaded box behind the bar.
 */
export interface CalibrationBand {
  readonly band: string;
  readonly stated_low: number;
  readonly stated_high: number;
  readonly agreement: Point;
  readonly volume: Point;
}

/** How sure the system said it was, against how often it was accepted. */
export interface Calibration {
  readonly title: string;
  readonly bands: readonly CalibrationBand[];
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly volume_domain: Domain;
  readonly summary: string;
}

/** A handful of named things, each with one figure. */
export interface BarChart {
  readonly title: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly bars: readonly Point[];
  readonly summary: string;
}

/**
 * One kind of claim: how often it came back ready, and how much of the work it is.
 *
 * `ready` is the share that went out exactly as produced. `volume` is how many decisions that
 * share was worked out from, so a reader can tell a real pattern from three claims that agreed.
 */
export interface ReadinessRow {
  readonly label: string;
  readonly ready: Point;
  readonly volume: Point;
}

/**
 * One way of cutting the claims up, with each part of it.
 *
 * `spread_text` says how far apart the readiest and least ready parts are, which is the measure
 * of whether the cut is worth anything at all: parts that all come back ready about as often
 * cannot tell anybody which claims to expect trouble from.
 */
export interface ReadinessGroup {
  readonly name: string;
  readonly spread_text: string;
  readonly rows: readonly ReadinessRow[];
}

/** Which kinds of claim come back ready to send, and which need a person. */
export interface Readiness {
  readonly title: string;
  readonly groups: readonly ReadinessGroup[];
  readonly domain: Domain;
  readonly summary: string;
}

/**
 * One candidate rule, scored.
 *
 * `verdict` is the service's own word, reshaped to read on screen rather than swapped for
 * wording of ours. Meeting the bar is not permission and there is deliberately nothing beside a
 * row to switch on.
 */
export interface GateRow {
  readonly value_band: string;
  readonly confidence_band: string;
  readonly decisions_text: string;
  readonly coverage_text: string;
  readonly agreement_text: string;
  readonly verdict: string;
}

/** Every candidate rule, in the order the service scored them. Never re-sorted here. */
export interface GateTable {
  readonly title: string;
  readonly columns: readonly string[];
  readonly rows: readonly GateRow[];
  readonly caveat: string;
}

/** One tile: a label, a figure already written out, and an optional line under it. */
export interface Figure {
  readonly label: string;
  readonly value: string;
  readonly note: string | null;
}

/** One number the reporting rests on that nobody has confirmed. */
export interface Assumption {
  readonly label: string;
  readonly value: string;
  readonly description: string;
}

/** One stretch of time the screen can ask for. */
export interface Preset {
  readonly key: string;
  readonly label: string;
  readonly applied: boolean;
}

/**
 * One part of the screen, which may have nothing to show.
 *
 * `data` is absent exactly when `empty_reason` is present, and the reason is a sentence because
 * an empty box reads as a screen that broke. A store that could not be read never arrives here —
 * that fails the whole request — so this is only ever "there was nothing", never "nobody looked".
 */
export interface Panel<Drawn> {
  readonly empty_reason: string | null;
  readonly data: Drawn | null;
}

/** Everything the analysis screen draws. */
export interface AnalysisView {
  readonly period_label: string;
  readonly starts_at: string;
  readonly ends_at: string;
  readonly presets: readonly Preset[];
  readonly hero: Figure;
  readonly figures: readonly Figure[];
  readonly savings: readonly Figure[];
  readonly assumptions: readonly Assumption[];
  readonly approval_trend: Panel<TimeChart>;
  readonly intervention_mix: Panel<StackedChart>;
  readonly calibration: Panel<Calibration>;
  readonly readiness: Panel<Readiness>;
  readonly disagreement: Panel<BarChart>;
  readonly review_time: Panel<TimeChart>;
  readonly gates: Panel<GateTable>;
  readonly generated_at: string;
}
