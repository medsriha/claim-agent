import { requestJson, sendJson } from "./request";
import type { ClearedStores, PolicyView, SubmittedValues } from "./policyTypes";

export async function fetchPolicy(): Promise<PolicyView> {
  return requestJson<PolicyView>("/admin/policy");
}

export async function savePolicy(values: SubmittedValues): Promise<PolicyView> {
  return sendJson<PolicyView>("/admin/policy", "PUT", { values });
}

export async function resetPolicy(): Promise<PolicyView> {
  return requestJson<PolicyView>("/admin/policy/reset", { method: "POST" });
}

export async function forgetEverything(): Promise<ClearedStores> {
  return requestJson<ClearedStores>("/admin/forget-everything", { method: "POST" });
}
