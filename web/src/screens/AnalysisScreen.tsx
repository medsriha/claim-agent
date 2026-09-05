/**
 * How the system has been doing, for the business.
 *
 * The other two screens are about one claim. This one is about all of them: over months, how
 * often a representative took the advice exactly as it stood, how far they changed it when they
 * did, how long it took, what that was worth, and whether the system's own statement of how sure
 * it was turns out to predict whether anyone agreed with it.
 *
 * **The screen works nothing out.** Every figure arrives from the service already worked out,
 * carried twice — once as a value to place a mark and once as the words to read. Nothing here
 * divides to make a percentage, adds a column up, decides where an axis stops, or turns an
 * amount of money into a number.
 *
 * **Nothing here is a control.** The candidate rules are scored and shown. There is no switch
 * beside any of them, because the requirements say a person approving a report is the only way a
 * claim is ever released, and no figure on this screen changes that.
 *
 * While a new period loads the old figures stay on screen, dimmed, still labelled with the period
 * they cover. Throwing away a year of figures because one request was slow would be a blank
 * screen with extra steps.
 */
import { useCallback, useEffect, useState } from "react";

import { fetchPerformance } from "../api/analysisClient";
import { ApiFailure } from "../api/failure";
import type { AnalysisView } from "../api/analysisTypes";
import { BandBarChart } from "../charts/BandBarChart";
import { StackedAreaChart } from "../charts/StackedAreaChart";
import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import {
  AutomationGates,
  FigureTiles,
  FilterRow,
  HeroFigure,
  PanelState,
  SavingsPanel,
} from "../components/AnalysisPanels";
import { FailureNotice } from "../components/FailureNotice";
import { formatMoment, humanise } from "../display";

/** The two lines on the approval chart: the investigated claims, then the ones stopped early. */
const TREND_TOKENS = ["--sb-chart-band-3", "--sb-chart-band-1"];

/** How far a representative went, palest for untouched through darkest for sent back. */
const MIX_TOKENS = [
  "--sb-chart-band-1",
  "--sb-chart-band-2",
  "--sb-chart-band-3",
  "--sb-chart-band-4",
];

export function AnalysisScreen(): React.JSX.Element {
  const [view, setView] = useState<AnalysisView | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  // Built already working, so the first read has nothing to set up front. An effect that changes
  // state as it runs makes the page draw twice before it has anything to show.
  const [busy, setBusy] = useState(true);
  const [period, setPeriod] = useState<string | null>(null);

  /** Ask for one period and draw the answer. Sets nothing before the request goes. */
  const send = useCallback((wanted: string | null): void => {
    fetchPerformance(wanted)
      .then((answer) => {
        setView(answer);
        setFailure(null);
      })
      .catch((error: unknown) => {
        // The client promises to throw only its own failure type. Anything else would be a bug
        // in this screen rather than a problem with the figures, and it still has to end in
        // something a person can act on rather than a blank page.
        setFailure(
          error instanceof ApiFailure
            ? error
            : new ApiFailure("unexpected", "This screen ran into a problem of its own."),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }, []);

  /** Start a request from a button: say the screen is working, then send it. */
  const run = useCallback(
    (wanted: string | null): void => {
      setBusy(true);
      send(wanted);
    },
    [send],
  );

  useEffect(() => {
    send(period);
  }, [send, period]);

  if (view === null) {
    return (
      <main className="screen screen-wide">
        {failure === null ? (
          <p className="working" role="status">
            Working out how things have been going…
          </p>
        ) : (
          <FailureNotice
            kind={failure.kind}
            message={failure.message}
            onRetry={() => {
              run(period);
            }}
          />
        )}
      </main>
    );
  }

  return (
    <main className="screen screen-wide">
      <FilterRow
        presets={view.presets}
        periodLabel={view.period_label}
        busy={busy}
        onPick={setPeriod}
      />

      {failure !== null && (
        <FailureNotice
          kind={failure.kind}
          message={failure.message}
          onRetry={() => {
            run(period);
          }}
        />
      )}

      <div className={busy ? "analysis-body analysis-stale" : "analysis-body"} aria-busy={busy}>
        <HeroFigure hero={view.hero} />
        <FigureTiles title={null} figures={view.figures} />
        <SavingsPanel savings={view.savings} assumptions={view.assumptions} />

        <PanelState panel={view.approval_trend}>
          {(chart) => <TimeSeriesChart chart={chart} tokens={TREND_TOKENS} height={250} />}
        </PanelState>

        <PanelState panel={view.intervention_mix}>
          {(chart) => <StackedAreaChart chart={chart} tokens={MIX_TOKENS} height={250} />}
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
              orientation="vertical"
              token="--sb-chart-band-3"
              height={286}
              sublabels={calibration.bands.map((band) => `${band.volume.text} decisions`)}
              legend={[
                { name: "How often it was accepted", token: "--sb-chart-band-3" },
                { name: "How sure the system said it was", token: "--sb-canvas" },
              ]}
              table={{
                columns: [
                  "How sure",
                  "The system said",
                  "Accepted",
                  "Decisions",
                ],
                rows: calibration.bands.map((band) => [
                  humanise(band.band),
                  band.stated_text,
                  band.agreement.text,
                  band.volume.text,
                ]),
              }}
            />
          )}
        </PanelState>

        <PanelState panel={view.disagreement}>
          {(chart) => (
            <BandBarChart
              title={chart.title}
              summary={chart.summary}
              bars={chart.bars}
              domain={chart.domain}
              gridlines={chart.gridlines}
              references={null}
              orientation="horizontal"
              token="--sb-chart-band-3"
              height={190}
              sublabels={null}
              legend={[]}
              table={{
                columns: ["What was recommended", "Changed"],
                rows: chart.bars.map((bar) => [humanise(bar.label), bar.text]),
              }}
            />
          )}
        </PanelState>

        <PanelState panel={view.review_time}>
          {(chart) => (
            <TimeSeriesChart chart={chart} tokens={["--sb-chart-band-3"]} height={230} />
          )}
        </PanelState>

        <PanelState panel={view.gates}>{(gates) => <AutomationGates gates={gates} />}</PanelState>

        <p className="analysis-generated">Worked out {formatMoment(view.generated_at)}.</p>
      </div>
    </main>
  );
}
