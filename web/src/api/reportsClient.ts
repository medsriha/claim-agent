import { ApiFailure, failureFrom, serviceUnreachable, unreadableAnswer } from "./failure";
import { requestJson } from "./request";
import type { Approval, Report, RevisionTurn, RunEvent } from "./types";

export async function approveReport(reportId: string, approval: Approval): Promise<Report> {
  return requestJson<Report>(`/reports/${encodeURIComponent(reportId)}/approve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(approval),
  });
}

/** The compact end of a feedback stream. A report version exists only when findings changed. */
export interface ReportRevisionResult {
  readonly report_id: string;
  readonly report_version: number | null;
  readonly revision: RevisionTurn;
}

type RevisionMessage =
  | { readonly kind: "progress"; readonly event: RunEvent }
  | { readonly kind: "result"; readonly result: ReportRevisionResult }
  | { readonly kind: "failed"; readonly code: string; readonly message: string }
  | { readonly kind: "done" };

/** Read a report only when a streamed answer says that its decision material changed. */
export async function readReport(reportId: string, version: number): Promise<Report> {
  return requestJson<Report>(
    `/reports/${encodeURIComponent(reportId)}?version=${encodeURIComponent(String(version))}`,
  );
}

/**
 * Send feedback and read the agent's progress as SSE.
 *
 * The final event contains the new conversation turn, not the whole report. If report content
 * changed it names the new version, which callers can fetch; a question-only answer names none.
 */
export async function sendReportBack(
  reportId: string,
  feedback: string,
  onProgress: (event: RunEvent) => void,
): Promise<ReportRevisionResult> {
  let response: Response;
  try {
    response = await fetch(`/reports/${encodeURIComponent(reportId)}/send-back`, {
      method: "POST",
      headers: { Accept: "text/event-stream", "content-type": "application/json" },
      body: JSON.stringify({ feedback }),
    });
  } catch {
    throw serviceUnreachable();
  }

  if (!response.ok) {
    throw await failureFrom(response);
  }
  if (response.body === null) {
    throw unreadableAnswer();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let unread = "";
  let result: ReportRevisionResult | null = null;
  let reportedFailure: ApiFailure | null = null;

  try {
    for (;;) {
      const read = await reader.read();
      if (read.done) {
        break;
      }
      unread += decoder.decode(read.value, { stream: true });
      const blocks = unread.split("\n\n");
      unread = blocks.pop() ?? "";
      for (const block of blocks) {
        const message = readRevisionMessage(block);
        if (message?.kind === "progress") {
          onProgress(message.event);
        } else if (message?.kind === "result") {
          result = message.result;
        } else if (message?.kind === "failed") {
          reportedFailure = new ApiFailure(failureKind(message.code), message.message);
        }
      }
    }
  } catch (error: unknown) {
    if (error instanceof ApiFailure) {
      throw error;
    }
    throw new ApiFailure("unexpected", "The agent's answer stopped part-way.");
  } finally {
    reader.releaseLock();
  }

  if (reportedFailure !== null) {
    throw reportedFailure;
  }
  if (result === null) {
    throw unreadableAnswer();
  }
  return result;
}

function readRevisionMessage(block: string): RevisionMessage | null {
  let name = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) {
      name = line.slice("event: ".length).trim();
    } else if (line.startsWith("data: ")) {
      data = line.slice("data: ".length);
    }
  }
  if (name === "" || data === "") {
    return null;
  }

  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  switch (name) {
    case "progress":
      return { kind: "progress", event: payload as RunEvent };
    case "result":
      return { kind: "result", result: payload as ReportRevisionResult };
    case "failed": {
      const failure = payload as { code?: string; message?: string };
      return {
        kind: "failed",
        code: failure.code ?? "unexpected",
        message: failure.message ?? "The agent could not answer.",
      };
    }
    case "done":
      return { kind: "done" };
    default:
      return null;
  }
}

function failureKind(code: string): "storage_unavailable" | "upstream_unavailable" | "unexpected" {
  if (code === "storage_unavailable") {
    return "storage_unavailable";
  }
  if (code === "upstream_unavailable") {
    return "upstream_unavailable";
  }
  return "unexpected";
}
