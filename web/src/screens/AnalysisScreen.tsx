/**
 * How the system has been doing, for the business.
 *
 * The other two screens are about one claim. This one is about all of them: over a year, how
 * often a representative took the advice exactly as it stood, how far they changed it when they
 * did, **which kinds of claim come back ready and which need a person**, how long it took, what
 * that was worth, and whether the system's own statement of how sure it was turns out to predict
 * whether anyone agreed with it.
 *
 * One year, and no way to ask for another. The service can report on shorter periods and the
 * shape it answers in still carries the choice, but a screen that carries its own figures would
 * have to carry a set for every period on offer, and three sets nobody switches between is weight
 * in the page for nothing.
 *
 * **Every figure on this screen is invented**, and nothing on screen says so. There is no real
 * history to draw, because the stage where a person decides a claim is not built. See
 * `analysis/demoFigures.ts`, which is where that is written down.
 *
 * **The screen still works nothing out.** Each figure arrives already worked out, carried twice —
 * once as a value to place a mark and once as the words to read. Nothing here divides to make a
 * percentage, adds a column up, decides where an axis stops, or turns an amount of money into a
 * number. That was worth keeping even with the figures held locally: it is what stops a chart and
 * the sentence beside it ever disagreeing.
 *
 * **Nothing here is a control.** Every panel reports and none of them offers anything to change:
 * no switch, no threshold to set, nothing to approve. The requirements say a person approving a
 * report is the only way a claim is ever released (FR-2.9, FR-3.1), and no figure on this screen
 * changes that. What it can do is say which claims tend to need that person and which do not.
 */
import { DEMO_FIGURES } from "../analysis/demoFigures";
import { BandBarChart } from "../charts/BandBarChart";
import { StackedAreaChart } from "../charts/StackedAreaChart";
import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import {
  FigureTiles,
  HeroFigure,
  PanelState,
  PeriodLine,
  SavingsPanel,
} from "../components/AnalysisPanels";
import { ReadinessPanel } from "../components/ReadinessPanel";
import { formatMoment } from "../display";

/** The four ways a decision can go. Four hues rather than four shades of one, so they can be
 *  told apart in a stack; the legend carries which is which. */
const MIX_TOKENS = ["--sb-chart-1", "--sb-chart-2", "--sb-chart-3", "--sb-chart-4"];

/** Everything drawn as a single series. */
const ONE_SERIES = ["--sb-chart-1"];

export function AnalysisScreen(): React.JSX.Element {
  const view = DEMO_FIGURES;

  return (
    <main className="screen screen-wide">
      <PeriodLine label={view.period_label} />

      <div className="analysis-body">
        <HeroFigure hero={view.hero} />
        <FigureTiles title={null} figures={view.figures} />
        <SavingsPanel savings={view.savings} />

        <PanelState panel={view.intervention_mix}>
          {(chart) => <StackedAreaChart chart={chart} tokens={MIX_TOKENS} height={250} />}
        </PanelState>

        <PanelState panel={view.readiness}>
          {(readiness) => <ReadinessPanel readiness={readiness} />}
        </PanelState>

        <PanelState panel={view.calibration}>
          {(calibration) => (
            <BandBarChart
              title={calibration.title}
              summary={calibration.summary}
              bars={calibration.bands.map((band) => band.agreement)}
              domain={calibration.domain}
              gridlines={calibration.gridlines}
              references={calibration.bands.map((band) => ({
                low: band.stated_low,
                high: band.stated_high,
              }))}
              token="--sb-chart-1"
              height={286}
              sublabels={calibration.bands.map(
                (band) => `${band.volume.text} decisions reviewed`,
              )}
              legend={[
                { name: "Accepted without changes", token: "--sb-chart-1" },
                { name: "AI confidence range", token: "--sb-canvas" },
              ]}
              table={{
                columns: ["AI confidence", "Accepted without changes", "Decisions reviewed"],
                rows: calibration.bands.map((band) => [
                  band.band,
                  band.agreement.text,
                  band.volume.text,
                ]),
              }}
            />
          )}
        </PanelState>

        <PanelState panel={view.review_time}>
          {(chart) => <TimeSeriesChart chart={chart} tokens={ONE_SERIES} height={230} />}
        </PanelState>

        <p className="analysis-generated">
          Dashboard data generated {formatMoment(view.generated_at)}.
        </p>
      </div>
    </main>
  );
}
