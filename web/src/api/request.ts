import { failureFrom, serviceUnreachable, unreadableAnswer } from "./failure";

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {

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

export async function sendJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
