/**
 * Reading how the system has been doing.
 *
 * One address, written down only here. The period is sent as a name the service itself listed —
 * never as a date — so the screen never works out a boundary of its own and two people asking
 * for "12 months" on the same day are shown the same window.
 */
import { requestJson } from "./request";
import type { AnalysisView } from "./analysisTypes";

/**
 * Read every figure for one stretch of time.
 *
 * @param period - A key from `presets` in an earlier reply, or `null` on the first load to take
 *   whichever period the service considers its default.
 * @returns Every tile, chart and table, with each figure carried both as a value to draw and as
 *   the words to read.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function fetchPerformance(period: string | null): Promise<AnalysisView> {
  const path =
    period === null
      ? "/analysis/performance"
      : `/analysis/performance?period=${encodeURIComponent(period)}`;
  return requestJson<AnalysisView>(path);
}
