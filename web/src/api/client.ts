import { requestJson, sendJson } from "./request";
import type { PrecedentSet, PreflightResult } from "./types";

/** Screen one claim. */
export async function screenCase(caseId: string): Promise<PreflightResult> {
  return requestJson<PreflightResult>(`/cases/${encodeURIComponent(caseId)}/preflight`, {
    method: "POST",
  });
}

/** Find past claims resembling the merchant's account. */
export async function findSimilarClaims(merchantAccount: string): Promise<PrecedentSet> {
  return sendJson<PrecedentSet>("/precedent/search", "POST", {
    merchant_account: merchantAccount,
  });
}
