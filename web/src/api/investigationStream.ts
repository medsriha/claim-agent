/**
 * Reading an investigation as it happens.
 *
 * The service reports what it is doing while it works, rather than going quiet and
 * answering at the end. This file reads that and hands each thing over as it arrives.
 *
 * **Why not the browser's own `EventSource`.** It only ever sends a GET, and asking for an
 * investigation is a POST — it is a step in the claim pipeline and will one day record
 * one. So the reply is read directly instead, which is a few more lines here and no change
 * to the service.
 *
 * **Nothing here interprets anything.** It splits the reply into the messages it carried
 * and passes them on untouched. Every sentence a representative reads was written by the
 * service; this file does not write, reorder, summarise or total anything.
 */
import { ApiFailure } from "./failure";
import type { ClaimInvestigation, PreflightResult, Report, RunEvent } from "./types";

/** What the service sends, one of these at a time. */
export type InvestigationMessage =
  /** Something the investigation did. Shown as it arrives. */
  | { readonly kind: "progress"; readonly event: RunEvent }
  /** Everything a representative decides from. Sent once, near the end. */
  | {
      readonly kind: "result";
      readonly screening: PreflightResult;
      /** The reports the service kept, ready to be decided on. Empty when it kept none. */
      readonly reports: readonly Report[];
      /** Why the findings could not be kept, or null when they were. */
      readonly reportsUnavailable: string | null;
      readonly investigation: ClaimInvestigation | null;
    }
  /** It went wrong, and this is the service's own account of why. */
  | { readonly kind: "failed"; readonly code: string; readonly message: string }
  /** Nothing more is coming. */
  | { readonly kind: "done" };

/** How a caller is handed each message as it arrives. */
export type OnMessage = (message: InvestigationMessage) => void;

/**
 * Ask for a claim to be investigated, and report back as it happens.
 *
 * @param caseId - The claim's case id, such as `CASE-1001`.
 * @param onMessage - Called once per message, in the order they arrived. Called from
 *   inside the read loop, so a caller that throws here stops the reading.
 * @throws ApiFailure - If the request itself never opened, or the connection broke
 *   part-way. A failure the service reported *inside* the stream arrives as a `failed`
 *   message instead, because by then it is an answer rather than a broken request.
 */
export async function investigateCase(caseId: string, onMessage: OnMessage): Promise<void> {
  const response = await openTheStream(caseId);
  const body = response.body;
  if (body === null) {
    throw new ApiFailure("unexpected", "The claims service sent nothing to read.");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  // Messages are separated by a blank line, and a read can stop in the middle of one, so
  // whatever is left over waits here for the rest of it to arrive.
  let unread = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      unread += decoder.decode(value, { stream: true });
      const blocks = unread.split("\n\n");
      // The last piece is either empty or an unfinished message. Either way it is not
      // ours to read yet.
      unread = blocks.pop() ?? "";
      for (const block of blocks) {
        const message = readOneMessage(block);
        if (message !== null) {
          onMessage(message);
        }
      }
    }
  } catch (error: unknown) {
    // The stream broke part-way. Whatever arrived before this still stands, so the caller
    // keeps it and shows this beside it rather than losing the lot (NFR-4).
    throw new ApiFailure(
      "unexpected",
      error instanceof Error && error.message !== ""
        ? `The investigation stopped part-way: ${error.message}`
        : "The investigation stopped part-way.",
    );
  } finally {
    reader.releaseLock();
  }
}

/**
 * Start the request, or fail in the same shape every other request on this screen fails in.
 *
 * A stream that opens says nothing about how the investigation went — a claim turned away
 * and a claim investigated in full both open normally. Only a request that never opened is
 * a failure here.
 */
async function openTheStream(caseId: string): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/cases/${encodeURIComponent(caseId)}/investigate`, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
    });
  } catch {
    throw new ApiFailure("unreachable", "The claims service could not be reached.");
  }

  if (!response.ok) {
    // The service refused before the stream began, so the reply is an ordinary error
    // rather than a stream. Its own words are worth more than anything we could add.
    throw new ApiFailure("unexpected", await refusalMessage(response));
  }
  return response;
}

/** Read the service's own sentence out of a refusal, or say plainly that it had none. */
async function refusalMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    const error = (body as { error?: { message?: string } }).error;
    if (typeof error?.message === "string" && error.message !== "") {
      return error.message;
    }
  } catch {
    // Not JSON, or nothing readable in it. Fall through to the plain sentence.
  }
  return `The claims service would not investigate this claim (${String(response.status)}).`;
}

/**
 * Turn one block of the reply into a message, or `null` if it is not one.
 *
 * The format is fixed by convention: a line naming the message, a line holding its data,
 * and a blank line ending it. Anything unrecognised is ignored rather than guessed at —
 * a message this screen cannot read is better skipped than half understood.
 */
function readOneMessage(block: string): InvestigationMessage | null {
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
    case "result": {
      const sent = payload as {
        screening: PreflightResult;
        investigation?: ClaimInvestigation;
        reports?: Report[];
        reports_unavailable_reason?: string | null;
      };
      return {
        kind: "result",
        screening: sent.screening,
        reports: sent.reports ?? [],
        reportsUnavailable: sent.reports_unavailable_reason ?? null,
        // Absent on a claim the checks turned away: it was never investigated, and
        // saying so is different from saying it was investigated and found nothing.
        investigation: sent.investigation ?? null,
      };
    }
    case "failed": {
      const sent = payload as { code?: string; message?: string };
      return {
        kind: "failed",
        code: sent.code ?? "unexpected",
        message: sent.message ?? "The investigation could not be completed.",
      };
    }
    case "done":
      return { kind: "done" };
    default:
      return null;
  }
}
