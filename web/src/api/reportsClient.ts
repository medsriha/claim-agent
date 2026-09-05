/**
 * Acting on a report the service kept.
 *
 * Two things a representative can do, and both are real: approving records that a person
 * accepted a recommendation, and sending one back records what they said was wrong. Neither
 * sends an email or moves money — the stage that would act on an approval does not exist
 * (FR-3.1), and nothing on this screen pretends otherwise.
 *
 * **No money is parsed here.** A figure goes out as the text it was typed as and comes back as
 * text. The service reads it into an exact decimal; a browser that turned it into a number
 * first would have already lost the cents (FR-1.21).
 */
import { requestJson } from "./request";
import type { Approval, Report } from "./types";

/** Approve a report, as it stands or after changing it (FR-2.8, FR-2.9). */
export async function approveReport(reportId: string, approval: Approval): Promise<Report> {
  return requestJson<Report>(`/reports/${encodeURIComponent(reportId)}/approve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(approval),
  });
}

/** Send a report back with a note saying what is wrong (FR-2.8, FR-R.1). */
export async function sendReportBack(reportId: string, feedback: string): Promise<Report> {
  return requestJson<Report>(`/reports/${encodeURIComponent(reportId)}/send-back`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
}
