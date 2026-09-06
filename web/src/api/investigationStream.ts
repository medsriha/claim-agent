import { ApiFailure } from "./failure";
import type { Report, RunEvent } from "./types";

export type InvestigationMessage =

  | { readonly kind: "progress"; readonly event: RunEvent }

  | {
      readonly kind: "result";

      readonly report: Report | null;

      readonly reportUnavailable: string | null;
    }

  | { readonly kind: "failed"; readonly code: string; readonly message: string }

  | { readonly kind: "done" };

export type OnMessage = (message: InvestigationMessage) => void;

export async function investigateCase(caseId: string, onMessage: OnMessage): Promise<void> {
  const response = await openTheStream(caseId);
  const body = response.body;
  if (body === null) {
    throw new ApiFailure("unexpected", "The claims service sent nothing to read.");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();

  let unread = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      unread += decoder.decode(value, { stream: true });
      const blocks = unread.split("\n\n");

      unread = blocks.pop() ?? "";
      for (const block of blocks) {
        const message = readOneMessage(block);
        if (message !== null) {
          onMessage(message);
        }
      }
    }
  } catch (error: unknown) {

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
        report?: Report | null;
        report_unavailable_reason?: string | null;
      };
      return {
        kind: "result",
        report: sent.report ?? null,
        reportUnavailable: sent.report_unavailable_reason ?? null,
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
