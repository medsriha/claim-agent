export interface Point {
  readonly value: number | null;
  readonly text: string;
  readonly label: string;
}

export interface Gridline {
  readonly at: number;
  readonly label: string;
}

export interface Domain {
  readonly minimum: number;
  readonly maximum: number;
}

export interface Series {
  readonly name: string;
  readonly points: readonly Point[];
}

export interface TimeChart {
  readonly title: string;
  readonly y_label: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly ticks: readonly number[];
  readonly series: readonly Series[];
  readonly summary: string;
}

export interface BandPoint {
  readonly upper: number | null;
  readonly text: string;
  readonly label: string;
}

export interface Band {
  readonly name: string;
  readonly points: readonly BandPoint[];
}

export interface StackedChart {
  readonly title: string;
  readonly y_label: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly ticks: readonly number[];
  readonly bands: readonly Band[];
  readonly summary: string;
}

export interface CalibrationBand {
  readonly band: string;
  readonly stated_low: number;
  readonly stated_high: number;
  readonly agreement: Point;
  readonly volume: Point;
}

export interface Calibration {
  readonly title: string;
  readonly bands: readonly CalibrationBand[];
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly volume_domain: Domain;
  readonly summary: string;
}

export interface BarChart {
  readonly title: string;
  readonly domain: Domain;
  readonly gridlines: readonly Gridline[];
  readonly bars: readonly Point[];
  readonly summary: string;
}

export interface ReadinessRow {
  readonly label: string;
  readonly ready: Point;
  readonly volume: Point;
}

export interface ReadinessGroup {
  readonly name: string;
  readonly spread_text: string;
  readonly rows: readonly ReadinessRow[];
}

export interface Readiness {
  readonly title: string;
  readonly groups: readonly ReadinessGroup[];
  readonly domain: Domain;
  readonly summary: string;
}

export interface GateRow {
  readonly value_band: string;
  readonly confidence_band: string;
  readonly decisions_text: string;
  readonly coverage_text: string;
  readonly agreement_text: string;
  readonly verdict: string;
}

export interface GateTable {
  readonly title: string;
  readonly columns: readonly string[];
  readonly rows: readonly GateRow[];
  readonly caveat: string;
}

export interface Figure {
  readonly label: string;
  readonly value: string;
  readonly note: string | null;
}

export interface Assumption {
  readonly label: string;
  readonly value: string;
  readonly description: string;
}

export interface Preset {
  readonly key: string;
  readonly label: string;
  readonly applied: boolean;
}

export interface Panel<Drawn> {
  readonly empty_reason: string | null;
  readonly data: Drawn | null;
}

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
