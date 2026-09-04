/**
 * Asking the claims service to screen a claim, and making sense of what comes back.
 *
 * The only place in the screen that knows an address or a status code. Failure gets as
 * much care as success: every way this can fail becomes one of a few named kinds, so the
 * screen can say something useful instead of showing raw error data.
 */
import type { PreflightResult } from "./types";

/**
 * The ways screening a claim can fail, as the person using it would see them.
 *
 * - `not_found` — no such case. Usually a typo.
 * - `upstream_unavailable` — ShipBob could not be read. Nothing is wrong with the claim.
 * - `unreachable` — the claims service itself did not answer.
 * - `unexpected` — anything else, kept separate rather than guessed at.
 */
export type FailureKind = "not_found" | "upstream_unavailable" | "unreachable" | "unexpected";

/**
 * A screening that could not be done. `message` is a finished sentence — the service's
 * own where it sent one, since it says these things more precisely than the screen could.
 */
export class ScreeningFailure extends Error {
  readonly kind: FailureKind;

  constructor(kind: FailureKind, message: string) {
    super(message);
    this.name = "ScreeningFailure";
    this.kind = kind;
  }
}

/** The error shape the service uses for every failure it reports on purpose. */
interface ErrorEnvelope {
  error: { code: string; message: string };
}

/** True if the parsed body is the service's error envelope. Checked, never assumed. */
function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== "object" || body === null || !("error" in body)) {
    return false;
  }
  const { error } = body;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "message" in error &&
    typeof (error as { code: unknown }).code === "string" &&
    typeof (error as { message: unknown }).message === "string"
  );
}

/**
 * Judge a failure whose body the service plainly did not write.
 *
 * Every failure the service reports carries its error envelope, whatever the status. So a
 * failing reply without one came from something in between — here, the dev server finding
 * nothing to forward to. Worth telling apart: it is the most common thing to hit locally,
 * and the fix is just to start the service.
 */
function unreadableFailure(status: number): ScreeningFailure {
  if (status >= 500) {
    return new ScreeningFailure(
      "unreachable",
      "The claims service could not be reached. Check that it is running.",
    );
  }
  return new ScreeningFailure(
    "unexpected",
    `The claims service answered with an error (${String(status)}).`,
  );
}

/** Turn a failing response into the named failure the screen knows how to show. */
async function failureFrom(response: Response): Promise<ScreeningFailure> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // A failure whose body is not readable is still a failure worth reporting properly.
    // The status is all we have to go on, so that is what it is judged on.
    return unreadableFailure(response.status);
  }

  if (!isErrorEnvelope(body)) {
    return unreadableFailure(response.status);
  }

  const { code, message } = body.error;
  if (code === "not_found") {
    return new ScreeningFailure("not_found", message);
  }
  if (code === "upstream_unavailable") {
    return new ScreeningFailure("upstream_unavailable", message);
  }
  return new ScreeningFailure("unexpected", message);
}

/**
 * Screen one claim. The case id is the whole request; there is nothing to send with it.
 *
 * @param caseId - The claim's case id, such as `CASE-1001`.
 * @returns What was read, what the four checks found, and the verdict. A stopped claim
 *   also carries the report a rep approves.
 * @throws ScreeningFailure - Always this and nothing else, so a caller has one kind of
 *   problem to handle.
 */
export async function screenCase(caseId: string): Promise<PreflightResult> {
  let response: Response;
  try {
    response = await fetch(`/cases/${encodeURIComponent(caseId)}/preflight`, { method: "POST" });
  } catch {
    // fetch only rejects when the request never got an answer at all: the service is
    // down, the network is gone. An answer we do not like is a resolved promise.
    throw new ScreeningFailure(
      "unreachable",
      "The claims service could not be reached. Check that it is running.",
    );
  }

  if (!response.ok) {
    throw await failureFrom(response);
  }

  try {
    return (await response.json()) as PreflightResult;
  } catch {
    throw new ScreeningFailure(
      "unexpected",
      "The claims service answered with something this screen could not read.",
    );
  }
}
