/**
 * Turning values into positions, and positions into shapes.
 *
 * Geometry only. Nothing here knows what a claim is, what a rate means, or which way is good —
 * it is handed numbers that were worked out in the service and returns coordinates. That is the
 * line this screen draws between rendering and deciding: turning a value into a length is
 * unavoidable in any chart, and everything upstream of it belongs in the service.
 *
 * Every coordinate goes out through `coord`, which trims it to two decimal places. That keeps
 * floating-point noise out of the path strings, and matches the project's habit of never letting
 * a raw number fall into a template.
 */

/** The space a chart's marks are drawn in, in real screen pixels. */
export interface Plot {
  readonly width: number;
  readonly height: number;
  readonly gutter: number;
  readonly padTop: number;
  readonly padRight: number;
  readonly axisBand: number;
}

/** Where an axis begins and ends, as the service sent it. */
export interface Span {
  readonly minimum: number;
  readonly maximum: number;
}

/** The usual spacing, shared so two charts stacked together line up exactly. */
export const PLOT: Omit<Plot, "width" | "height"> = {
  gutter: 44,
  padTop: 14,
  padRight: 18,
  axisBand: 26,
};

/** Trim a coordinate for a path string. */
export function coord(value: number): string {
  return value.toFixed(2);
}

/**
 * Nudge a line onto a single row of pixels.
 *
 * A one-pixel line drawn on a whole number straddles two device pixels and renders as a grey
 * two-pixel smudge. Half a pixel over puts it on one.
 */
export function crisp(value: number): number {
  return Math.round(value) + 0.5;
}

/** The left edge of the drawable area. */
export function left(plot: Plot): number {
  return plot.gutter;
}

/** The right edge of the drawable area. */
export function right(plot: Plot): number {
  return Math.max(plot.gutter, plot.width - plot.padRight);
}

/** The bottom of the drawable area, which is where the axis sits. */
export function bottom(plot: Plot): number {
  return Math.max(plot.padTop, plot.height - plot.axisBand);
}

/** How far up the plot a value sits. */
export function scaleY(plot: Plot, span: Span, value: number): number {
  const floor = bottom(plot);
  const reach = span.maximum - span.minimum;
  if (reach <= 0) {
    return floor;
  }
  const share = (value - span.minimum) / reach;
  return floor - share * (floor - plot.padTop);
}

/**
 * How far across the plot the point at `index` sits.
 *
 * A single point is put in the middle rather than hard against the left edge, where it would
 * read as the start of a line that never got drawn.
 */
export function scaleX(plot: Plot, count: number, index: number): number {
  const from = left(plot);
  const to = right(plot);
  if (count <= 1) {
    return (from + to) / 2;
  }
  return from + (index / (count - 1)) * (to - from);
}

/** Evenly spaced band centres, for a chart whose positions are categories rather than dates. */
export function bandCentre(plot: Plot, count: number, index: number): number {
  const from = left(plot);
  const to = right(plot);
  if (count <= 0) {
    return from;
  }
  const width = (to - from) / count;
  return from + width * (index + 0.5);
}

/** How wide one category's slot is, before any cap on the mark inside it. */
export function bandWidth(plot: Plot, count: number): number {
  if (count <= 0) {
    return 0;
  }
  return (right(plot) - left(plot)) / count;
}

/**
 * Draw a line through the values, breaking wherever there is nothing to draw.
 *
 * A gap stays a gap: no bridge, no interpolation, no drop to the floor. A week in which nobody
 * decided anything has no rate, and joining across it would draw a claim nobody made.
 */
export function linePath(
  values: readonly (number | null)[],
  plot: Plot,
  span: Span,
): string {
  const parts: string[] = [];
  let drawing = false;
  values.forEach((value, index) => {
    if (value === null) {
      drawing = false;
      return;
    }
    const x = coord(scaleX(plot, values.length, index));
    const y = coord(scaleY(plot, span, value));
    parts.push(`${drawing ? "L" : "M"} ${x} ${y}`);
    drawing = true;
  });
  return parts.join(" ");
}

/**
 * Fill the strip between one band's top edge and the band below it.
 *
 * Both edges arrive already added up by the service. A run of weeks with nothing in them ends
 * the shape and starts a new one, so all the bands break together and none is drawn across a
 * week that held nothing.
 */
export function bandPath(
  upper: readonly (number | null)[],
  lower: readonly (number | null)[],
  plot: Plot,
  span: Span,
): string {
  const shapes: string[] = [];
  let run: number[] = [];

  const close = (): void => {
    if (run.length === 0) {
      return;
    }
    const top = run.map((index) => {
      const value = upper[index] ?? span.minimum;
      return `L ${coord(scaleX(plot, upper.length, index))} ${coord(scaleY(plot, span, value))}`;
    });
    const back = [...run].reverse().map((index) => {
      const value = lower[index] ?? span.minimum;
      return `L ${coord(scaleX(plot, upper.length, index))} ${coord(scaleY(plot, span, value))}`;
    });
    shapes.push(`M${top.join(" ").slice(1)} ${back.join(" ")} Z`);
    run = [];
  };

  upper.forEach((value, index) => {
    if (value === null) {
      close();
      return;
    }
    run.push(index);
  });
  close();
  return shapes.join(" ");
}

/**
 * A bar with its data end rounded and its baseline end square.
 *
 * The radius is clamped to the bar's own length. A bar shorter than the radius drawn with a
 * fixed one produces a self-crossing path, which renders as a dark hook rather than a small bar —
 * and a chart of rates will always eventually contain a very small bar.
 */
export function barPath(
  baseline: number,
  end: number,
  across: number,
  thickness: number,
  direction: "up" | "right",
): string {
  const length = Math.abs(end - baseline);
  const radius = Math.min(4, length);
  const far = across + thickness;

  if (radius < 1) {
    return direction === "up"
      ? `M ${coord(across)} ${coord(baseline)} L ${coord(far)} ${coord(baseline)} L ${coord(far)} ${coord(end)} L ${coord(across)} ${coord(end)} Z`
      : `M ${coord(baseline)} ${coord(across)} L ${coord(baseline)} ${coord(far)} L ${coord(end)} ${coord(far)} L ${coord(end)} ${coord(across)} Z`;
  }

  if (direction === "up") {
    const towards = end < baseline ? 1 : -1;
    return [
      `M ${coord(across)} ${coord(baseline)}`,
      `L ${coord(across)} ${coord(end + radius * towards)}`,
      `Q ${coord(across)} ${coord(end)} ${coord(across + radius)} ${coord(end)}`,
      `L ${coord(far - radius)} ${coord(end)}`,
      `Q ${coord(far)} ${coord(end)} ${coord(far)} ${coord(end + radius * towards)}`,
      `L ${coord(far)} ${coord(baseline)}`,
      "Z",
    ].join(" ");
  }

  const towards = end > baseline ? -1 : 1;
  return [
    `M ${coord(baseline)} ${coord(across)}`,
    `L ${coord(end + radius * towards)} ${coord(across)}`,
    `Q ${coord(end)} ${coord(across)} ${coord(end)} ${coord(across + radius)}`,
    `L ${coord(end)} ${coord(far - radius)}`,
    `Q ${coord(end)} ${coord(far)} ${coord(end + radius * towards)} ${coord(far)}`,
    `L ${coord(baseline)} ${coord(far)}`,
    "Z",
  ].join(" ");
}

/** Which point a pointer at `x` is nearest, so a reader aims at a date and not at a line. */
export function nearestIndex(plot: Plot, count: number, x: number): number {
  if (count <= 1) {
    return 0;
  }
  const from = left(plot);
  const to = right(plot);
  const share = (x - from) / Math.max(1, to - from);
  return Math.min(count - 1, Math.max(0, Math.round(share * (count - 1))));
}
