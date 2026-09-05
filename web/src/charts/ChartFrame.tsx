/**
 * The shell every chart on the analysis screen is drawn inside.
 *
 * It owns the parts that must be the same everywhere: the heading, the switch between the chart
 * and the same figures as a table, the legend, the box the drawing is measured into, the tooltip,
 * and the line of text under the plot that says what is picked out.
 *
 * Two of those are not decoration. **The table is the same figures without the picture**, so no
 * value on this screen is only reachable by hovering — which also covers the reader for whom a
 * pale fill on white is hard to see. And **the readout is the tooltip in words**, updated when
 * the keyboard moves rather than when the pointer does, because a spoken region driven by mouse
 * movement is unusable and a pointer user can already see the tooltip.
 *
 * The drawing is never scaled: the box is measured and the picture drawn at exactly that size,
 * so the type inside it is the size the stylesheet asked for. See `useChartWidth`.
 */
import { useId, useState } from "react";

import { PLOT, scaleY } from "./plot";
import type { Plot } from "./plot";
import { useChartTooltip } from "./useChartTooltip";
import type { Active } from "./useChartTooltip";
import { useChartWidth } from "./useChartWidth";

/** One entry in a chart's key: a coloured mark and the word beside it. */
export interface LegendItem {
  readonly name: string;
  readonly token: string;
}

/** One row of a tooltip: a coloured mark, what it is, and the figure. */
export interface TipRow {
  readonly token: string | null;
  readonly name: string;
  readonly value: string;
}

/** The same figures as a table, which is what stops a value being reachable only by hovering. */
export interface TableTwin {
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

/** What a chart is given to draw its marks into. */
export interface Surface {
  readonly plot: Plot;
  readonly active: Active | null;
  readonly show: (index: number, source: "pointer" | "keyboard") => void;
  readonly clear: () => void;
}

interface ChartFrameProps {
  title: string;
  /** The service's sentence about the whole chart, shown when nothing is picked out. */
  summary: string;
  /** Fixed, and **including the band the x-axis labels sit in**, so no card grows a scrollbar. */
  height: number;
  /**
   * How much room to leave under the plot for the labels.
   *
   * A chart writing two lines under each position needs more than one writing a single date, and
   * getting this wrong does not clip the text — it lets the marks run over it.
   */
  axisBand: number;
  /** How many positions there are along the chart, for the arrow keys and the nearest-point find. */
  count: number;
  /** Empty for a single series: there is one colour, and the title already says what it is. */
  legend: readonly LegendItem[];
  gridlines: readonly { at: number; label: string }[];
  domain: { minimum: number; maximum: number };
  table: TableTwin;
  /** Where along the plot the position at `index` sits, so the tooltip can find it. */
  xFor: (plot: Plot, index: number) => number;
  /** What the tooltip says about a position. */
  tipFor: (index: number) => { heading: string; rows: readonly TipRow[] };
  children: (surface: Surface) => React.ReactNode;
}

export function ChartFrame({
  title,
  summary,
  height,
  axisBand,
  count,
  legend,
  gridlines,
  domain,
  table,
  xFor,
  tipFor,
  children,
}: ChartFrameProps): React.JSX.Element {
  const [asTable, setAsTable] = useState(false);
  const { box, width } = useChartWidth();
  const tooltip = useChartTooltip(count);
  const titleId = useId();

  const plot: Plot = { ...PLOT, axisBand, width, height };
  const active = tooltip.active;
  const tip = active === null ? null : tipFor(active.index);

  return (
    <section className="panel chart-card">
      <div className="chart-head">
        <h3 className="panel-title" id={titleId}>
          {title}
        </h3>
        <div className="chart-views" role="group" aria-label="How to show this">
          <ViewChip label="Chart" picked={!asTable} onPick={setAsTable} to={false} />
          <ViewChip label="Table" picked={asTable} onPick={setAsTable} to={true} />
        </div>
      </div>

      {legend.length > 0 && (
        <ul className="chart-legend">
          {legend.map((item) => (
            <li className="legend-item" key={item.name}>
              <span
                className="legend-mark"
                style={{ background: `var(${item.token})` }}
                aria-hidden="true"
              />
              <span className="legend-word">{item.name}</span>
            </li>
          ))}
        </ul>
      )}

      {asTable ? (
        <Twin table={table} />
      ) : (
        <>
          <div className="chart-plot" ref={box} style={{ height: `${String(height)}px` }}>
            {width > 0 && (
              <svg
                className="chart-svg"
                width={width}
                height={height}
                viewBox={`0 0 ${String(width)} ${String(height)}`}
                role="img"
                aria-labelledby={titleId}
                focusable="false"
              >
                <Gridlines plot={plot} domain={domain} lines={gridlines} />
                {children({ plot, active, show: tooltip.show, clear: tooltip.clear })}
              </svg>
            )}

            {/* One focus stop for the whole chart. The arrow keys walk the points. */}
            <div
              className="chart-focus"
              tabIndex={0}
              role="group"
              aria-label={`${title}. Use the arrow keys to read each point.`}
              onKeyDown={tooltip.onKeyDown}
              onBlur={tooltip.clear}
            />

            {tip !== null && width > 0 && (
              <div
                className="chart-tip"
                style={tipPosition(xFor(plot, active?.index ?? 0), width)}
                aria-hidden="true"
              >
                <p className="chart-tip-head">{tip.heading}</p>
                {tip.rows.map((row) => (
                  <p className="chart-tip-row" key={row.name}>
                    {row.token !== null && (
                      <span
                        className="chart-tip-mark"
                        style={{ background: `var(${row.token})` }}
                        aria-hidden="true"
                      />
                    )}
                    <span className="chart-tip-name">{row.name}</span>
                    <span className="chart-tip-value">{row.value}</span>
                  </p>
                ))}
              </div>
            )}
          </div>

          <p className="chart-readout" role="status" aria-live="polite">
            {active?.source === "keyboard" && tip !== null
              ? `${tip.heading}. ${tip.rows.map((row) => `${row.name}: ${row.value}`).join(". ")}`
              : summary}
          </p>
        </>
      )}
    </section>
  );
}

/** Keep the tooltip inside the card by flipping it past the halfway point. */
function tipPosition(x: number, width: number): React.CSSProperties {
  return x > width / 2
    ? { right: `${String(Math.round(width - x))}px` }
    : { left: `${String(Math.round(x))}px` };
}

interface ViewChipProps {
  label: string;
  picked: boolean;
  to: boolean;
  onPick: (asTable: boolean) => void;
}

/** One half of the chart-or-table switch. */
function ViewChip({ label, picked, to, onPick }: ViewChipProps): React.JSX.Element {
  return (
    <button
      className={picked ? "chip chip-picked" : "chip"}
      type="button"
      aria-pressed={picked}
      onClick={() => {
        onPick(to);
      }}
    >
      {label}
    </button>
  );
}

/** The same figures as a table, using the table the rest of the project already uses. */
function Twin({ table }: { table: TableTwin }): React.JSX.Element {
  return (
    <div className="table-scroll">
      <table className="lines">
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.join("|")}>
              {row.map((cell, position) => (
                <td className={position === 0 ? undefined : "numeric"} key={`${row.join("|")}-${String(position)}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface GridlinesProps {
  plot: Plot;
  domain: { minimum: number; maximum: number };
  lines: readonly { at: number; label: string }[];
}

/** The rules across the plot, and the words at the end of them. Solid hairlines, never dashed. */
function Gridlines({ plot, domain, lines }: GridlinesProps): React.JSX.Element {
  return (
    <g>
      {lines.map((line) => {
        const y = Math.round(scaleY(plot, domain, line.at)) + 0.5;
        return (
          <g key={line.label}>
            <line
              className="chart-grid-line"
              x1={plot.gutter}
              y1={y}
              x2={Math.max(plot.gutter, plot.width - plot.padRight)}
              y2={y}
            />
            <text className="chart-label" x={plot.gutter - 8} y={y + 4} textAnchor="end">
              {line.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}
