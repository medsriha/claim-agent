/**
 * Reading and changing the claim policy — the numbers every claim is judged by.
 *
 * Three addresses, and they are only written down here. Each answers with the whole
 * policy as it now stands, so the panel never has to work out what its own change did:
 * it draws whatever came back.
 */
import { requestJson, sendJson } from "./request";
import type { ClearedStores, PolicyView, SubmittedValues } from "./policyTypes";

/**
 * Read the policy in force.
 *
 * @returns Every value, with the service's own explanation of it, what it holds now, and
 *   what it held when the service started.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function fetchPolicy(): Promise<PolicyView> {
  return requestJson<PolicyView>("/admin/policy");
}

/**
 * Change the policy. Takes effect on the next claim screened — nothing is restarted.
 *
 * The whole form is sent, not only the boxes somebody touched. It costs nothing, and it
 * means the panel never has to decide what counts as a change; the service compares what
 * arrives with what it holds.
 *
 * @param values - Every value on the form, by name. Numbers and amounts of money are
 *   text, exactly as they were typed.
 * @returns The policy now in force.
 * @throws ApiFailure - Always this and nothing else. A refused change carries one
 *   complaint per value in `problems`, and nothing at all was changed.
 */
export async function savePolicy(values: SubmittedValues): Promise<PolicyView> {
  return sendJson<PolicyView>("/admin/policy", "PUT", { values });
}

/**
 * Put back the values the service started with.
 *
 * @returns The policy now in force, which is the one the service started with.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function resetPolicy(): Promise<PolicyView> {
  return requestJson<PolicyView>("/admin/policy/reset", { method: "POST" });
}

/**
 * Throw away everything the service has remembered.
 *
 * **A demonstration control that destroys real history.** Four stores go: what representatives
 * corrected for each merchant, every report and every earlier version of one, what
 * representatives decided, and the past claims a new claim is priced against. That is the point
 * when somebody wants to show the system starting from nothing, and a genuine loss otherwise.
 * There is no undo.
 *
 * @returns How many records went from each store. All zeroes is an ordinary answer.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function forgetEverything(): Promise<ClearedStores> {
  return requestJson<ClearedStores>("/admin/forget-everything", { method: "POST" });
}
