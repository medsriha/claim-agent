import { ChartFrame } from "./ChartFrame";
import type { Surface, TipRow } from "./ChartFrame";
import { PLOT, bottom, coord, crisp, left, linePath, nearestIndex, right, scaleX, scaleY } from "./plot";
import type { TimeChart } from "../api/analysisTypes";

interface TimeSeriesChartProps {
  chart: TimeChart;

  tokens: readonly string[];
  height: number;
}

export function TimeSeriesChart({ chart, tokens, height }: TimeSeriesChartProps): React.JSX.Element {
  const first = chart.series[0];
  const count = first?.points.length ?? 0;

  const tipFor = (index: number): { heading: string; rows: readonly TipRow[] } => ({
    heading: first?.points[index]?.label ?? "",
    rows: chart.series.map(
      (series, position): TipRow => ({
        token: tokens[position] ?? null,
        name: series.name,
        value: series.points[index]?.text ?? "—",
      }),
    ),
  });

  return (
    <ChartFrame
      title={chart.title}
      summary={chart.summary}
      height={height}
      axisBand={PLOT.axisBand}
      count={count}
      legend={
        chart.series.length > 1
          ? chart.series.map((series, position) => ({
              name: series.name,
              token: tokens[position] ?? "--sb-chart-band-2",
            }))
          : []
      }
      gridlines={chart.gridlines}
      domain={chart.domain}
      table={{
        columns: ["Week", ...chart.series.map((series) => series.name)],
        rows: Array.from({ length: count }, (_unused, index) => [
          first?.points[index]?.label ?? "",
          ...chart.series.map((series) => series.points[index]?.text ?? "—"),
        ]),
      }}
      xFor={(plot, index) => scaleX(plot, count, index)}
      tipFor={tipFor}
    >
      {(surface) => <Marks chart={chart} tokens={tokens} surface={surface} count={count} />}
    </ChartFrame>
  );
}

interface MarksProps {
  chart: TimeChart;
  tokens: readonly string[];
  surface: Surface;
  count: number;
}

function Marks({ chart, tokens, surface, count }: MarksProps): React.JSX.Element {
  const { plot, active, show, clear } = surface;
  const floor = crisp(bottom(plot));
  const first = chart.series[0];

  return (
    <g>
      <line className="chart-axis-line" x1={left(plot)} y1={floor} x2={right(plot)} y2={floor} />

      {chart.ticks.map((index) => (
        <text
          className="chart-label"
          key={index}
          x={scaleX(plot, count, index)}
          y={plot.height - 8}
          textAnchor={tickAnchor(index, count)}
        >
          {first?.points[index]?.label.replace("week of ", "") ?? ""}
        </text>
      ))}

      {active !== null && (
        <line
          className="chart-crosshair"
          x1={crisp(scaleX(plot, count, active.index))}
          y1={plot.padTop}
          x2={crisp(scaleX(plot, count, active.index))}
          y2={floor}
        />
      )}

      {chart.series.map((series, position) => (
        <path
          key={series.name}
          d={linePath(
            series.points.map((point) => point.value),
            plot,
            chart.domain,
          )}
          fill="none"
          stroke={`var(${tokens[position] ?? "--sb-chart-band-2"})`}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}

      {active !== null &&
        chart.series.map((series, position) => {
          const value = series.points[active.index]?.value;
          if (value === null || value === undefined) {
            return null;
          }
          return (
            <circle
              key={series.name}
              cx={coord(scaleX(plot, count, active.index))}
              cy={coord(scaleY(plot, chart.domain, value))}
              r="4.5"
              fill={`var(${tokens[position] ?? "--sb-chart-band-2"})`}
              stroke="var(--sb-surface)"
              strokeWidth="2"
            />
          );
        })}

      <rect
        x={left(plot)}
        y={plot.padTop}
        width={Math.max(0, right(plot) - left(plot))}
        height={Math.max(0, bottom(plot) - plot.padTop)}
        fill="transparent"
        onPointerMove={(event) => {
          const at = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
          if (at !== undefined) {
            show(nearestIndex(plot, count, event.clientX - at.left), "pointer");
          }
        }}
        onPointerLeave={clear}
      />
    </g>
  );
}

/** Keep the first and last labels from hanging off the ends of the plot. */
function tickAnchor(index: number, count: number): "start" | "middle" | "end" {
  if (index === 0) {
    return "start";
  }
  if (index === count - 1) {
    return "end";
  }
  return "middle";
}
