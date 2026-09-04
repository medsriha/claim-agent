/**
 * What a failed request to the claims service becomes, wherever it was sent from.
 *
 * Both screens talk to the service, and both need the same care taken over failure:
 * every way a request can go wrong ends up as one of a few named kinds, so a screen can
 * say something a person is able to act on instead of showing raw error data. A blank
 * screen is a bug.
 */

/**
 * The ways a request can fail, as the person using it would see them.
 *
 * - `not_found` — no such case. Usually a typo.
 * - `upstream_unavailable` — ShipBob could not be read. Nothing is wrong with the claim.
 * - `invalid_request` — the service refused what was sent. Only the policy panel can
 *   cause this, by submitting a value the claim policy will not accept.
 * - `unreachable` — the claims service itself did not answer.
 * - `unexpected` — anything else, kept separate rather than guessed at.
 */
export type FailureKind =
  | "not_found"
  | "upstream_unavailable"
  | "invalid_request"
  | "unreachable"
  | "unexpected";

/**
 * One value the service refused, and its complaint about that value.
 *
 * Only the policy panel gets these. A change is refused value by value, so the panel can
 * put each complaint beside the box it belongs to rather than leaving someone to work
 * out which of eleven values it meant.
 */
export interface ValueProblem {
  name: string;
  message: string;
}

/**
 * A request that could not be completed. `message` is a finished sentence — the
 * service's own wherever it sent one, since it says these things more precisely than a
 * screen could.
 */
export class ApiFailure extends Error {
  readonly kind: FailureKind;
  readonly problems: readonly ValueProblem[];

  constructor(kind: FailureKind, message: string, problems: readonly ValueProblem[] = []) {
    super(message);
    this.name = "ApiFailure";
    this.kind = kind;
    this.problems = problems;
  }
}

/** The service never answered. Locally this nearly always means it is not running. */
export function serviceUnreachable(): ApiFailure {
  return new ApiFailure(
    "unreachable",
    "The claims service could not be reached. Check that it is running.",
  );
}

/** An answer arrived, but not one this screen could make sense of. */
export function unreadableAnswer(): ApiFailure {
  return new ApiFailure(
    "unexpected",
    "The claims service answered with something this screen could not read.",
  );
}

/** The error shape the service uses for every failure it reports on purpose. */
interface ErrorEnvelope {
  error: { code: string; message: string; details?: unknown };
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

/** True if one entry in the details is a complaint about a named value. */
function isValueProblem(entry: unknown): entry is ValueProblem {
  return (
    typeof entry === "object" &&
    entry !== null &&
    "name" in entry &&
    "message" in entry &&
    typeof (entry as { name: unknown }).name === "string" &&
    typeof (entry as { message: unknown }).message === "string"
  );
}

/**
 * Read the list of refused values out of a failure's details, if it carries one.
 *
 * Everything here is checked rather than trusted. The details are free-form by design —
 * each kind of failure puts what it needs in there — so a screen reading them has to
 * cope with them not being what it hoped for.
 */
function problemsIn(envelope: ErrorEnvelope): ValueProblem[] {
  const { details } = envelope.error;
  if (typeof details !== "object" || details === null || !("values" in details)) {
    return [];
  }
  // Reachable without a cast: checking the key is there is what tells the type checker
  // this object has one.
  const listed: unknown = details.values;
  if (!isList(listed)) {
    return [];
  }
  return listed.filter(isValueProblem);
}

/** True if this is a list of anything. Its entries stay unknown until each is checked. */
function isList(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

/**
 * Judge a failure whose body the service plainly did not write.
 *
 * Every failure the service reports carries its error envelope, whatever the status. So
 * a failing reply without one came from something in between — here, the dev server
 * finding nothing to forward to. Worth telling apart: it is the most common thing to hit
 * locally, and the fix is just to start the service.
 */
function unreadableFailure(status: number): ApiFailure {
  if (status >= 500) {
    return serviceUnreachable();
  }
  return new ApiFailure(
    "unexpected",
    `The claims service answered with an error (${String(status)}).`,
  );
}

/** Which named kind a code the service sent belongs to. Anything unknown stays apart. */
function kindOf(code: string): FailureKind {
  if (code === "not_found") {
    return "not_found";
  }
  if (code === "upstream_unavailable") {
    return "upstream_unavailable";
  }
  if (code === "invalid_request") {
    return "invalid_request";
  }
  return "unexpected";
}

/** Turn a failing response into the named failure a screen knows how to show. */
export async function failureFrom(response: Response): Promise<ApiFailure> {
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
  return new ApiFailure(kindOf(code), message, problemsIn(body));
}
