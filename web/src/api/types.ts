/**
 * The shapes the claims service sends back.
 *
 * Every name matches a field the service actually sends, with nothing renamed on the way
 * in, so this can be read side by side with the Python models and checked against them.
 *
 * Two things to know:
 *
 * - **Money is text, never a number.** `"90.00"` arrives as text because the service works
 *   it out exactly and a browser number cannot hold it that way. Keeping it as text means
 *   nothing on screen can do arithmetic with it by accident.
 * - **`null` means something.** An order that could not be read has no value, which is not
 *   the same as an order worth nothing.
 *
 * Times are text in the international standard shape, always UTC.
 */

/** Whether the claim may be investigated, or is stopped here. */
export type Verdict = "proceed" | "terminal";

/** The four eligibility checks every claim goes through. */
export type GateName = "age" | "claim_type" | "key_information" | "insurance";

/** Why a claim was stopped. A claim can collect more than one. */
export type TerminalReason =
  | "shipment_insured"
  | "claim_too_old"
  | "wrong_claim_type"
  | "missing_key_information";

/**
 * What one check found. `explanation` is a finished sentence; `observed` holds the values
 * it looked at, so the finding can be checked rather than trusted. `reason` is filled in
 * only when the check failed.
 */
export interface GateResult {
  gate: GateName;
  passed: boolean;
  reason: TerminalReason | null;
  explanation: string;
  observed: Record<string, string>;
}

/** One product on the order. `unit_price` is text — see the note at the top. */
export interface OrderLineItem {
  product_id: string | null;
  name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
}

/**
 * The order the damaged goods came from. There is no total here on purpose: the service
 * works it out and sends it in the claim context. Adding these lines up on screen is what
 * the project forbids.
 */
export interface Order {
  order_id: string;
  user_id: string | null;
  line_items: OrderLineItem[];
  created_date: string | null;
}

/** The parcel: how it travelled, where it got to, and whether it was insured. */
export interface Shipment {
  shipment_id: string;
  is_insured: boolean;
  order_id: string | null;
  carrier: string | null;
  tracking_number: string | null;
  status: string | null;
  delivered_date: string | null;
}

/** The case the merchant opened, in their words, with the ids it points at. */
export interface Case {
  case_id: string;
  created_date: string;
  status: string | null;
  sub_category: string | null;
  description: string | null;
  order_id: string | null;
  user_id: string | null;
  shipment_id: string | null;
  delivered_date: string | null;
  contact_email: string | null;
  account_name: string | null;
}

/**
 * Everything the screening read. `shipment` and `order` are `null` when the case named
 * none, or when the record could not be read.
 */
export interface CaseRecord {
  case: Case;
  shipment: Shipment | null;
  order: Order | null;
}

/** Something a rep changed on an earlier claim from the same merchant. */
export interface MerchantCorrection {
  user_id: string;
  case_id: string;
  summary: string;
  recorded_at: string;
}

/**
 * Facts worked out up front. `days_since_delivery` counts delivery to the day the claim
 * was filed, not to today, so it never goes stale. `is_high_value` is false when the value
 * is unknown, meaning "not known to be" rather than "known not to be".
 */
export interface ClaimContext {
  order_value_usd: string | null;
  is_high_value: boolean;
  days_since_delivery: number | null;
  delivered_date: string | null;
  merchant_corrections: MerchantCorrection[];
}

/**
 * An email written to the merchant that has not been sent and cannot send itself.
 *
 * `is_draft` can only be true. The email's own words never say "draft", so a marker can
 * never reach a merchant — which makes the screen the only place that state is visible.
 * `to` is `null` when the case carries no contact address.
 */
export interface DraftedEmail {
  to: string | null;
  subject: string;
  body: string;
  is_draft: true;
}

/**
 * What a rep receives when a claim cannot be processed.
 *
 * There are two things they can be handed, and a claim may carry either or both:
 *
 * - **`drafted_email`**, for every reason the merchant can be told about. `null` when
 *   there is nothing to tell them, which today means a claim stopped only by being
 *   insured.
 * - **`requires_escalation`**, true when the claim has to leave this process entirely.
 *   Insured shipments are claimed on their insurance somewhere else, so they are routed
 *   out rather than answered, and no email is written about it.
 *
 * A claim that is both insured and, say, too old carries both, and the rep chooses. The
 * screen shows whichever it was given and never decides between them.
 *
 * `reasons` lists every reason the claim was stopped, insured first when it applies, then
 * in the order the email explains the rest — so they are never sorted on screen.
 */
export interface TerminalReport {
  case_id: string;
  account_name: string | null;
  user_id: string | null;
  reasons: TerminalReason[];
  findings: string[];
  gates: GateResult[];
  context: ClaimContext;
  drafted_email: DraftedEmail | null;
  requires_escalation: boolean;
  requires_rep_approval: true;
}

/**
 * The complete answer for one claim. `report` is filled in only when the claim was
 * stopped; `gates` carries all four checks either way.
 */
export interface PreflightResult {
  case_id: string;
  verdict: Verdict;
  terminal_reasons: TerminalReason[];
  gates: GateResult[];
  record: CaseRecord;
  context: ClaimContext;
  report: TerminalReport | null;
  evaluated_at: string;
}

/** How the damaged product related to the order it came from. */
export type MatchOutcome = "matched" | "not_on_order" | "ambiguous";

/** What a claim line closed on. */
export type Recommendation = "approve" | "request_info" | "deny" | "escalate";

/**
 * One damaged product whose claim was closed.
 *
 * **Everything here was decided by a representative.** A claim still in review has no
 * outcome and is never stored, so there is no such thing as a record nobody agreed to and
 * nothing to weigh differently.
 *
 * `unit_price` and `amount_usd` are text — see the note at the top. `outcome` is what the
 * claim actually closed on, and `amount_usd` is what was paid — `null` when it paid nothing.
 */
export interface PrecedentRecord {
  precedent_id: string;
  case_id: string;
  claim_line_id: string;
  user_id: string | null;
  product_name: string;
  sku: string | null;
  unit_price: string | null;
  merchant_account: string | null;
  match: MatchOutcome;
  outcome: Recommendation;
  amount_usd: string | null;
  cap_applied: boolean;
  rep_note: string | null;
  withdrawn: boolean;
  closed_at: string;
}

/**
 * How alike two claims are, and why. `reasons` are the service's own sentences, so a
 * representative can disagree with the comparison rather than take it on trust.
 */
export interface PrecedentSimilarity {
  score: number;
  reasons: string[];
}

/** One past claim that was found to be similar, with the score and reasons behind it. */
export interface RetrievedPrecedent {
  record: PrecedentRecord;
  similarity: PrecedentSimilarity;
}

/**
 * What a search for similar claims found.
 *
 * **`was_read` is the field to check before saying anything.** True means the store was
 * read, whether or not it held anything; false means it could not be read at all, and
 * `unavailable_reason` says so in the service's own words. An empty `retrieved` means
 * different things in the two cases, and telling somebody there is no comparable history
 * when nobody looked is the one wrong answer.
 */
export interface PrecedentSet {
  retrieved: RetrievedPrecedent[];
  considered: number;
  unavailable_reason: string | null;
  was_read: boolean;
}
