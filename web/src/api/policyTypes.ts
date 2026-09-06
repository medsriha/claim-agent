interface PolicyValueCommon {
  name: string;
  description: string;
  changed: boolean;
}

export interface PolicyValueWritten extends PolicyValueCommon {
  kind: "integer" | "money" | "fraction" | "text";
  value: string;
  startup_value: string;
}

export interface PolicyValueChoice extends PolicyValueCommon {
  kind: "choice";
  value: string;
  startup_value: string;
  options: string[];
}

export interface PolicyValueYesNo extends PolicyValueCommon {
  kind: "boolean";
  value: boolean;
  startup_value: boolean;
}

export type PolicyValue = PolicyValueWritten | PolicyValueChoice | PolicyValueYesNo;

export interface PolicyView {
  values: PolicyValue[];
  changed_at: string | null;
  matches_startup: boolean;
}

type SubmittedValue = string | boolean;

export type SubmittedValues = Record<string, SubmittedValue>;

export interface ClearedStores {
  readonly corrections: number;
  readonly reports: number;
  readonly decisions: number;
  readonly past_claims: number;
}
