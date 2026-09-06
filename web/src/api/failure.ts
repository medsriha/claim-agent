export type FailureKind =
  | "not_found"
  | "upstream_unavailable"
  | "invalid_request"
  | "storage_unavailable"
  | "unreachable"
  | "unexpected";

export interface ValueProblem {
  name: string;
  message: string;
}

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

export function serviceUnreachable(): ApiFailure {
  return new ApiFailure(
    "unreachable",
    "The claims service could not be reached. Check that it is running.",
  );
}

export function unreadableAnswer(): ApiFailure {
  return new ApiFailure(
    "unexpected",
    "The claims service answered with something this screen could not read.",
  );
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: unknown };
}

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

function problemsIn(envelope: ErrorEnvelope): ValueProblem[] {
  const { details } = envelope.error;
  if (typeof details !== "object" || details === null || !("values" in details)) {
    return [];
  }

  const listed: unknown = details.values;
  if (!isList(listed)) {
    return [];
  }
  return listed.filter(isValueProblem);
}

function isList(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

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
  if (code === "storage_unavailable") {
    return "storage_unavailable";
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
