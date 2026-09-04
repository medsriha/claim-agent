/**
 * Asking the claims service to screen a claim.
 *
 * The address lives here and nowhere else. How a request is sent, and what happens when
 * it fails, is next door in `request.ts` — shared with the policy panel, so both screens
 * fail the same way.
 */
import { requestJson } from "./request";
import type { PreflightResult } from "./types";

/**
 * Screen one claim. The case id is the whole request; there is nothing to send with it.
 *
 * @param caseId - The claim's case id, such as `CASE-1001`.
 * @returns What was read, what the four checks found, and the verdict. A stopped claim
 *   also carries the report a rep approves.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function screenCase(caseId: string): Promise<PreflightResult> {
  return requestJson<PreflightResult>(`/cases/${encodeURIComponent(caseId)}/preflight`, {
    method: "POST",
  });
}
