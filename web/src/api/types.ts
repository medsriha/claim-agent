/**
 * The shapes the claims service sends back, written out for the screen to read.
 *
 * Every name here matches a field the service actually sends. Nothing is renamed on the
 * way in, so a reader can hold this file and the service's own definitions side by side
 * and check them against each other.
 *
 * Two habits are worth knowing before reading it:
 *
 * - **Money is text, never a number.** `"90.00"` arrives as text because the service
 *   works money out exactly and a browser number cannot hold it that way — 0.1 + 0.2 is
 *   famously not 0.3. Keeping it as text means nothing on the screen can accidentally do
 *   arithmetic with it.
 * - **A missing value is `null`, and it means something.** An order that could not be
 *   read has no value, which is a different thing from an order worth nothing. The
 *   screen has to say which it is looking at.
 *
 * Times arrive as text in the international standard shape, always on the UTC clock.
 */

/** Whether the claim may be investigated, or is stopped here. */
export type Verdict = "proceed" | "terminal";

/** The four eligibility checks every claim goes through. */
export type GateName = "age" | "claim_type" | "key_information" | "insurance";

/** Why a claim was stopped. A claim can collect more than one of these. */
export type TerminalReason =
  | "shipment_insured"
  | "claim_too_old"
  | "wrong_claim_type"
  | "missing_key_information";

/**
 * What one of the four checks found.
 *
 * `explanation` is a finished sentence a rep can read as it is. `observed` holds every
 * value the check actually looked at, so its finding can be verified rather than taken
 * on trust. `reason` is filled in only on a check that failed.
 */
export interface GateResult {
  gate: GateName;
  passed: boolean;
  reason: TerminalReason | null;
  explanation: string;
  observed: Record<string, string>;
}

/** One product on the order. `unit_price` is text; see the note at the top of this file. */
export interface OrderLineItem {
  product_id: string | null;
  name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
}

/**
 * The order the damaged goods came from.
 *
 * There is no total here, and that is deliberate rather than an oversight: the service
 * works the total out and sends it as part of the claim context. Adding these lines up
 * on screen is exactly what the project forbids.
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

/** The support case the merchant opened, in their words, with the ids it points at. */
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
 * Everything the screening read.
 *
 * `shipment` and `order` are `null` when the case named none, or when the record could
 * not be read at all.
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
 * The facts worked out up front, so nothing later has to work them out again.
 *
 * `days_since_delivery` counts delivery to the day the claim was filed — not to today —
 * so the number never goes stale. `is_high_value` is false when the value is unknown,
 * meaning "not known to be high value" rather than "known to be ordinary".
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
 * `is_draft` can only ever be true. The email's own words never say "draft", so that a
 * marker can never reach a merchant by accident — which makes this screen the only place
 * the draft state is visible, and why it is stated so plainly there.
 *
 * `to` is `null` when the case carries no contact address. The draft is still written;
 * a rep supplies the address before approving it.
 */
export interface DraftedEmail {
  to: string | null;
  subject: string;
  body: string;
  is_draft: true;
}

/**
 * What a rep receives when a claim cannot be processed at all.
 *
 * `reasons` are in order of precedence — the first is the one that heads the merchant's
 * email — so the screen shows them in the order they arrive and never sorts them.
 * `findings` is one sentence per failed check. `gates` carries all four, passed and
 * failed alike.
 */
export interface TerminalReport {
  case_id: string;
  account_name: string | null;
  user_id: string | null;
  reasons: TerminalReason[];
  findings: string[];
  gates: GateResult[];
  context: ClaimContext;
  drafted_email: DraftedEmail;
  requires_rep_approval: true;
}

/**
 * The complete answer for one claim.
 *
 * `report` is filled in only when the claim was stopped, and `terminal_reasons` is empty
 * on one allowed through. `gates` carries all four checks either way.
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
