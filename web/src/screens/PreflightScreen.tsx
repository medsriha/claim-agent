/**
 * The one screen: type a case id, see what the eligibility checks decided.
 *
 * It holds the whole of the screen's state, which is four things — what is being
 * screened, whether a screening is running, the last result, and the last failure. There
 * is only ever one of a result or a failure, never both, because a new screening clears
 * whatever the last one left behind. Showing a stale verdict next to a fresh error would
 * be worse than showing nothing.
 *
 * Nothing is kept between visits. Closing the page loses the result, because there is
 * nowhere to keep one yet.
 */
import { useCallback, useState } from "react";

import { ScreeningFailure, screenCase } from "../api/client";
import { CaseLookup } from "../components/CaseLookup";
import { ClaimContextPanel } from "../components/ClaimContextPanel";
import { FailureNotice } from "../components/FailureNotice";
import { GateList } from "../components/GateList";
import { RecordPanel } from "../components/RecordPanel";
import { EvaluatedAt, TerminalReportPanel } from "../components/TerminalReportPanel";
import { VerdictBanner } from "../components/VerdictBanner";
import type { PreflightResult } from "../api/types";

export function PreflightScreen(): React.JSX.Element {
  const [screenedId, setScreenedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PreflightResult | null>(null);
  const [failure, setFailure] = useState<ScreeningFailure | null>(null);

  const run = useCallback((caseId: string): void => {
    setScreenedId(caseId);
    setBusy(true);
    setResult(null);
    setFailure(null);

    screenCase(caseId)
      .then((screened) => {
        setResult(screened);
      })
      .catch((error: unknown) => {
        // The client promises to throw only its own failure type. Anything else would be
        // a bug in this screen rather than a problem with the claim, and it still has to
        // end in something readable rather than a blank page.
        setFailure(
          error instanceof ScreeningFailure
            ? error
            : new ScreeningFailure("unexpected", "This screen ran into a problem of its own."),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }, []);

  const retry = useCallback((): void => {
    if (screenedId !== null) {
      run(screenedId);
    }
  }, [run, screenedId]);

  return (
    <main className="screen">
      <CaseLookup onScreen={run} busy={busy} />

      {busy && (
        <p className="working" role="status">
          Screening {screenedId ?? "the claim"}…
        </p>
      )}

      {!busy && failure !== null && (
        <FailureNotice kind={failure.kind} message={failure.message} onRetry={retry} />
      )}

      {!busy && result !== null && (
        <div className="result">
          <VerdictBanner
            caseId={result.case_id}
            verdict={result.verdict}
            reasons={result.terminal_reasons}
          />
          {result.report !== null && <TerminalReportPanel report={result.report} />}
          <GateList gates={result.gates} />
          <ClaimContextPanel context={result.context} />
          <RecordPanel record={result.record} />
          <EvaluatedAt moment={result.evaluated_at} />
        </div>
      )}

      {!busy && result === null && failure === null && (
        <section className="intro">
          <h2 className="intro-title">Screen a damaged-in-transit claim</h2>
          <p>
            Every claim is checked four ways before anyone investigates it: whether it was
            filed soon enough, whether it is the right kind of claim, whether the parcel,
            the order and the merchant&rsquo;s description are all there, and whether the
            parcel was insured. The checks are fixed rules, so the same claim always gets
            the same answer, and no AI is involved at this stage.
          </p>
          <p>
            Enter a case id above, or pick one of the samples, to see what they found.
          </p>
        </section>
      )}
    </main>
  );
}
