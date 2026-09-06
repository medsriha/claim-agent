import { ChartFrame } from "./ChartFrame";
import type { Surface, TipRow } from "./ChartFrame";
import { PLOT, bandPath, bottom, crisp, left, right, scaleX } from "./plot";
import type { StackedChart } from "../api/analysisTypes";

interface StackedAreaChartProps {
  chart: StackedChart;

  tokens: readonly string[];
  height: number;
}

export function StackedAreaChart({
  chart,
  tokens,
  height,
}: StackedAreaChartProps): React.JSX.Element {
  const first = chart.bands[0];
  const count = first?.points.length ?? 0;

  return (
    <ChartFrame
      title={chart.title}
      summary={chart.summary}
      showSummary={false}
      height={height}
      axisBand={PLOT.axisBand}
      count={count}
      legend={chart.bands.map((band, position) => ({
        name: band.name,
        token: tokens[position] ?? "--sb-chart-band-2",
      }))}
      gridlines={chart.gridlines}
      domain={chart.domain}
      table={{
        columns: ["Week", ...chart.bands.map((band) => band.name)],
        rows: Array.from({ length: count }, (_unused, index) => [
          weekLabel(chart, index),
          ...chart.bands.map((band) => band.points[index]?.text ?? "—"),
        ]),
      }}
      xFor={(plot, index) => scaleX(plot, count, index)}
      tipFor={(index) => ({
        heading: weekLabel(chart, index),
        rows: chart.bands.map(
          (band, position): TipRow => ({
            token: tokens[position] ?? null,
            name: band.name,
            value: band.points[index]?.text ?? "—",
          }),
        ),
      })}
    >
      {(surface) => <Bands chart={chart} tokens={tokens} surface={surface} count={count} />}
    </ChartFrame>
  );
}

function weekLabel(chart: StackedChart, index: number): string {
  return chart.bands[0]?.points[index]?.label ?? "";
}

interface BandsProps {
  chart: StackedChart;
  tokens: readonly string[];
  surface: Surface;
  count: number;
}

function Bands({ chart, tokens, surface, count }: BandsProps): React.JSX.Element {
  const { plot, active, show, clear } = surface;
  const floor = crisp(bottom(plot));

  return (
    <g>
      <line className="chart-axis-line" x1={left(plot)} y1={floor} x2={right(plot)} y2={floor} />

      {chart.ticks.map((index) => (
        <text
          className="chart-label"
          key={index}
          x={scaleX(plot, count, index)}
          y={plot.height - 8}
          textAnchor={index === 0 ? "start" : index === count - 1 ? "end" : "middle"}
        >
          {weekLabel(chart, index).replace("week of ", "")}
        </text>
      ))}

      {chart.bands.map((band, position) => {
        const below = chart.bands[position - 1];
        return (
          <path
            key={band.name}
            d={bandPath(
              band.points.map((point) => point.upper),
              below === undefined
                ? band.points.map(() => chart.domain.minimum)
                : below.points.map((point) => point.upper),
              plot,
              chart.domain,
            )}
            fill={`var(${tokens[position] ?? "--sb-chart-band-2"})`}
            /* The surface-coloured hairline is the gap between touching fills. A border drawn
               around a mark would be ink that is not data. */
            stroke="var(--sb-surface)"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        );
      })}

      {active !== null && (
        <line
          className="chart-crosshair"
          x1={crisp(scaleX(plot, count, active.index))}
          y1={plot.padTop}
          x2={crisp(scaleX(plot, count, active.index))}
          y2={floor}
        />
      )}

      <rect
        x={left(plot)}
        y={plot.padTop}
        width={Math.max(0, right(plot) - left(plot))}
        height={Math.max(0, bottom(plot) - plot.padTop)}
        fill="transparent"
        onPointerMove={(event) => {
          const at = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
          if (at !== undefined) {
            const share = (event.clientX - at.left - left(plot)) / Math.max(1, right(plot) - left(plot));
            show(Math.min(count - 1, Math.max(0, Math.round(share * (count - 1)))), "pointer");
          }
        }}
        onPointerLeave={clear}
      />
    </g>
  );
}
