/**
 * The one place in the screen that talks to the network.
 *
 * Every request the screens make goes through here, so there is a single answer to
 * "what happens when the service is down", "what happens when it says no", and "what
 * happens when the reply is not what we expected". Callers get either the answer they
 * asked for or one named failure, and never have to look at a status code.
 */
import { failureFrom, serviceUnreachable, unreadableAnswer } from "./failure";

/**
 * Send one request to the claims service and read its answer.
 *
 * @param path - The address, as the service offers it — the dev server forwards it on.
 * @param init - Anything to send: the method, and a body for the requests that have one.
 * @returns The answer, taken at its word. Nothing here checks the answer's shape: the
 *   service and this screen are typed from the same field names, and a mismatch is a
 *   change somebody made on purpose rather than something to guard every reply against.
 * @throws ApiFailure - Always this and nothing else, so a caller has one kind of problem
 *   to handle whichever way the request went wrong.
 */
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    // fetch only rejects when the request never got an answer at all: the service is
    // down, the network is gone. An answer we do not like is a resolved promise.
    throw serviceUnreachable();
  }

  if (!response.ok) {
    throw await failureFrom(response);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw unreadableAnswer();
  }
}

/** Send a request whose body is JSON. The one shape of write these screens make. */
export async function sendJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
