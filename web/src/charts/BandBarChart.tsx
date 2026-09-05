/**
 * A handful of named things, each with one figure.
 *
 * Used three ways on this screen: how often each recommendation was changed (lying on its side,
 * because four names read better beside their bars than squeezed under them), and the two halves
 * of the calibration panel.
 *
 * **The categories here are nominal**, so every bar is the same colour and the labels do the
 * telling apart. Colouring each bar differently would spend the one channel that carries identity
 * on information the bar's length already shows.
 */
import { ChartFrame } from "./ChartFrame";
import type { Surface, TableTwin, TipRow } from "./ChartFrame";
import {
  PLOT,
  bandCentre,
  bandWidth,
  barPath,
  bottom,
  crisp,
  left,
  right,
  scaleY,
} from "./plot";
import type { Point } from "../api/analysisTypes";
import { humanise } from "../display";

/** A range to shade behind a bar, for showing what was claimed against what happened. */
export interface Reference {
  readonly low: number;
  readonly high: number;
}

interface BandBarChartProps {
  title: string;
  summary: string;
  bars: readonly Point[];
  domain: { minimum: number; maximum: number };
  gridlines: readonly { at: number; label: string }[];
  /** One per bar, or `null` for no shading. Same length as `bars` when given. */
  references: readonly Reference[] | null;
  orientation: "vertical" | "horizontal";
  token: string;
  height: number;
  table: TableTwin;
  /** What the shaded range means, when there is one. Empty for no legend. */
  legend: readonly { name: string; token: string }[];
  /**
   * A second line under each category name, or `null`.
   *
   * This is how a second measure is shown without a second scale. How many decisions a band held
   * matters for reading the bar above it, but a count and a rate must never share an axis — the
   * point where two such lines crossed would be an accident of scaling that a reader would take
   * for meaning. So the count is written, not drawn.
   */
  sublabels: readonly string[] | null;
}

export function BandBarChart({
  title,
  summary,
  bars,
  domain,
  gridlines,
  references,
  orientation,
  token,
  height,
  table,
  legend,
  sublabels,
}: BandBarChartProps): React.JSX.Element {
  return (
    <ChartFrame
      title={title}
      summary={summary}
      height={height}
      axisBand={sublabels === null ? PLOT.axisBand : 42}
      count={bars.length}
      legend={legend}
      gridlines={orientation === "vertical" ? gridlines : []}
      domain={domain}
      table={table}
      xFor={(plot, index) =>
        orientation === "vertical"
          ? bandCentre(plot, bars.length, index)
          : (left(plot) + right(plot)) / 2
      }
      tipFor={(index) => ({
        heading: humanise(bars[index]?.label ?? ""),
        rows: [{ token, name: "Figure", value: bars[index]?.text ?? "—" }] as readonly TipRow[],
      })}
    >
      {(surface) => (
        <Bars
          bars={bars}
          domain={domain}
          references={references}
          orientation={orientation}
          token={token}
          surface={surface}
          sublabels={sublabels}
        />
      )}
    </ChartFrame>
  );
}

interface BarsProps {
  bars: readonly Point[];
  domain: { minimum: number; maximum: number };
  references: readonly Reference[] | null;
  orientation: "vertical" | "horizontal";
  token: string;
  surface: Surface;
  sublabels: readonly string[] | null;
}

function Bars({
  bars,
  domain,
  references,
  orientation,
  token,
  surface,
  sublabels,
}: BarsProps): React.JSX.Element {
  const { plot, active, show, clear } = surface;

  if (orientation === "horizontal") {
    return <Lying bars={bars} domain={domain} token={token} surface={surface} />;
  }

  const floor = crisp(bottom(plot));
  const slot = bandWidth(plot, bars.length);
  const thickness = Math.min(24, slot * 0.42);

  return (
    <g>
      <line className="chart-axis-line" x1={left(plot)} y1={floor} x2={right(plot)} y2={floor} />

      {bars.map((bar, index) => {
        const centre = bandCentre(plot, bars.length, index);
        const across = centre - thickness / 2;
        const reference = references?.[index];
        const picked = active?.index === index;

        return (
          <g key={bar.label}>
            {/* What the system claimed, shaded behind what actually happened. Not a series, so
                it takes the page's own background rather than a colour of its own. */}
            {reference !== undefined && (
              <rect
                x={centre - slot * 0.34}
                y={scaleY(plot, domain, reference.high)}
                width={slot * 0.68}
                height={Math.max(
                  0,
                  scaleY(plot, domain, reference.low) - scaleY(plot, domain, reference.high),
                )}
                fill="var(--sb-canvas)"
                stroke="var(--sb-line)"
                strokeWidth="1"
                rx="3"
              />
            )}

            {bar.value !== null && (
              <path
                d={barPath(floor, scaleY(plot, domain, bar.value), across, thickness, "up")}
                fill={`var(${token})`}
                opacity={picked ? 0.82 : 1}
              />
            )}

            <text
              className="chart-value-label"
              x={centre}
              y={
                bar.value === null
                  ? floor - 8
                  : Math.max(plot.padTop + 10, scaleY(plot, domain, bar.value) - 8)
              }
              textAnchor="middle"
            >
              {bar.text}
            </text>

            <text
              className="chart-label"
              x={centre}
              y={plot.height - (sublabels === null ? 8 : 24)}
              textAnchor="middle"
            >
              {humanise(bar.label)}
            </text>

            {sublabels !== null && (
              <text className="chart-sublabel" x={centre} y={plot.height - 7} textAnchor="middle">
                {sublabels[index] ?? ""}
              </text>
            )}

            {/* The target is the whole slot, so nobody has to land on a thin bar. */}
            <rect
              x={centre - slot / 2}
              y={plot.padTop}
              width={slot}
              height={Math.max(0, bottom(plot) - plot.padTop)}
              fill="transparent"
              onPointerEnter={() => {
                show(index, "pointer");
              }}
              onPointerLeave={clear}
            />
          </g>
        );
      })}
    </g>
  );
}

interface LyingProps {
  bars: readonly Point[];
  domain: { minimum: number; maximum: number };
  token: string;
  surface: Surface;
}

/** Bars on their side, so four long names read straight rather than turned on end. */
function Lying({ bars, domain, token, surface }: LyingProps): React.JSX.Element {
  const { plot, active, show, clear } = surface;
  const baseline = crisp(left(plot) + 76);
  const usable = Math.max(1, right(plot) - baseline - 44);
  const slot = Math.max(0, (plot.height - plot.padTop) / Math.max(1, bars.length));
  const thickness = Math.min(24, slot * 0.42);

  return (
    <g>
      <line
        className="chart-axis-line"
        x1={baseline}
        y1={plot.padTop}
        x2={baseline}
        y2={plot.padTop + slot * bars.length}
      />

      {bars.map((bar, index) => {
        const across = plot.padTop + slot * index + (slot - thickness) / 2;
        const share = bar.value === null ? 0 : (bar.value - domain.minimum) / Math.max(0.0001, domain.maximum - domain.minimum);
        const end = baseline + share * usable;

        return (
          <g key={bar.label}>
            <text
              className="chart-label"
              x={baseline - 8}
              y={across + thickness / 2 + 4}
              textAnchor="end"
            >
              {humanise(bar.label)}
            </text>

            {bar.value !== null && (
              <path
                d={barPath(baseline, end, across, thickness, "right")}
                fill={`var(${token})`}
                opacity={active?.index === index ? 0.82 : 1}
              />
            )}

            <text
              className="chart-value-label"
              x={end + 8}
              y={across + thickness / 2 + 4}
              textAnchor="start"
            >
              {bar.text}
            </text>

            <rect
              x={baseline}
              y={plot.padTop + slot * index}
              width={Math.max(0, right(plot) - baseline)}
              height={slot}
              fill="transparent"
              onPointerEnter={() => {
                show(index, "pointer");
              }}
              onPointerLeave={clear}
            />
          </g>
        );
      })}
    </g>
  );
}
