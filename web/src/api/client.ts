/**
 * Asking the claims service to screen a claim, and making sense of what comes back.
 *
 * This is the only place in the screen that talks to the service. Everything else works
 * from the result it hands back, which is why no component anywhere else has to know
 * about addresses, status codes or error shapes.
 *
 * Failure gets as much care here as success. A claim that cannot be screened is an
 * ordinary thing for a rep to run into — a mistyped id, ShipBob having a bad morning —
 * and each of those needs something different from the person reading it. So every
 * failure is turned into one of a few named kinds, and the screen says what to do about
 * each. Nothing here ever ends in a blank page or raw error data on screen.
 */
import type { PreflightResult } from "./types";

/**
 * The ways screening a claim can fail, from the point of view of someone using it.
 *
 * - `not_found` — ShipBob has no such case. Usually a typo, and the rep can fix it.
 * - `upstream_unavailable` — ShipBob could not be reached or would not answer. Nothing
 *   is wrong with the claim; trying again later is the right move.
 * - `unreachable` — the browser could not reach the claims service itself. In a demo
 *   this almost always means the service is not running.
 * - `unexpected` — anything else. Kept separate so it is never quietly shown as one of
 *   the others, because being told the wrong thing is worse than being told very little.
 */
export type FailureKind = "not_found" | "upstream_unavailable" | "unreachable" | "unexpected";

/**
 * A screening that could not be done, in a form the screen can render.
 *
 * `message` is a finished sentence. Where the service supplied one it is used as it
 * stands, because the service says these things more precisely than the screen could
 * guess; where it did not, this file supplies one.
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

/**
 * True if the parsed body is the service's error envelope.
 *
 * Checked rather than assumed: anything can be sitting on a port, and a screen that
 * trusts an unknown reply will show whatever it happens to contain.
 */
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
 * Every failure the service reports on purpose carries its error envelope, whatever the
 * status. So a failing reply *without* one did not come from the service at all — it came
 * from something in between, which in this demo is the development server finding nothing
 * to forward to. That is worth telling apart, because it is far and away the most common
 * thing to hit when running this locally and the fix is simply to start the service.
 *
 * Anything else is left as unexpected rather than guessed at: being told the wrong cause
 * is worse than being told very little.
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
 * Screen one claim and hand back everything the checks found.
 *
 * The case id is the whole request; there is nothing to send with it. Asked for as a
 * POST because screening is a step in handling a claim, and will record one once there
 * is anywhere to record it.
 *
 * @param caseId - The claim's case id, such as `CASE-1001`.
 * @returns What was read, what each of the four checks found, and the verdict. A stopped
 *   claim also carries the report a rep has to approve.
 * @throws ScreeningFailure - Always this, and never anything else, so that every caller
 *   has exactly one kind of problem to handle.
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
