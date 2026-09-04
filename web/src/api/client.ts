/**
 * Asking the claims service to screen a claim.
 *
 * The address lives here and nowhere else. How a request is sent, and what happens when
 * it fails, is next door in `request.ts` — shared with the policy panel, so both screens
 * fail the same way.
 */
import { requestJson, sendJson } from "./request";
import type { PrecedentSet, PreflightResult } from "./types";

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

/**
 * Find the past claims that resemble this one.
 *
 * Only the merchant's own description is sent, because at this point it is all the screen
 * has: the claim has not been split into products yet, so there is no product or price to
 * compare on. Which claims count as similar is the service's judgement entirely.
 *
 * @param merchantAccount - What the merchant said happened, in their words.
 * @returns The past claims found, most alike first, each with the reasons behind it — or an
 *   empty set that says whether the store was read or could not be.
 * @throws ApiFailure - Always this and nothing else.
 */
export async function findSimilarClaims(merchantAccount: string): Promise<PrecedentSet> {
  return sendJson<PrecedentSet>("/precedent/search", "POST", {
    merchant_account: merchantAccount,
  });
}
