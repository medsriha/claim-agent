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

/** One image attached to the claim, including the URL the report links to. */
export interface Attachment {
  attachment_id: string;
  url: string;
  file_name: string | null;
  content_type: string | null;
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
 * - **`requires_rep_clarification`**, true when the rep must resolve the internal path.
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
  requires_rep_clarification: boolean;
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
export type Recommendation = "approve" | "request_info" | "request_rep_clarification";

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

// ---------------------------------------------------------------------------
// Investigating a claim — what arrives while the work happens, and what it ends with
// ---------------------------------------------------------------------------

/**
 * The kinds of thing an investigation says about itself as it works.
 *
 * Listed here so the screen can label them, and for no other reason: it never decides
 * anything from the kind. A kind it does not recognise is still shown, because the
 * sentence beside it is the service's own and is worth reading whatever we call it.
 */
export type RunEventKind =
  | "screened"
  | "attachments_listed"
  | "image_classified"
  | "evidence_settled"
  | "claim_split"
  | "precedent_gathered"
  | "line_started"
  | "tool_called"
  | "thinking"
  | "line_finished"
  | "report_ready"
  | "failed";

/**
 * One thing the investigation said while it was working.
 *
 * `summary` is a finished sentence written by the service, ready to put on screen
 * unchanged. `claim_line_id` names the damaged product it is about, and is `null` for the
 * things that concern the whole claim — several products are investigated at once, so
 * without it there would be no telling which of them a line belonged to.
 */
export interface RunEvent {
  sequence: number;
  kind: RunEventKind;
  summary: string;
  claim_line_id: string | null;
  detail: Record<string, string>;
}

/** One damaged product, as the claim was split into products. */
export interface ClaimLine {
  claim_line_id: string;
  claimed: { name: string; quantity: number; sku: string | null };
  match: "matched" | "not_on_order" | "ambiguous";
  order_line: OrderLineItem | null;
  candidate_order_lines: OrderLineItem[];
  damage_attachment_ids: string[];
}

/** What was found for one of the four pieces of evidence, and in which image. */
export interface EvidenceFinding {
  kind: "invoice" | "customer_confirmation" | "damaged_product_photo" | "outer_packaging_photo";
  state: "present" | "missing" | "unusable" | "unreadable";
  observed: string;
  attachment_id: string | null;
  problem: string | null;
}

/** One of the four judgements, with the reasoning that makes it reviewable. */
export interface Assessment {
  name:
    | "damage_visible"
    | "product_identifiable"
    | "product_on_invoice"
    | "packaging_documented";
  passed: boolean;
  reasoning: string;
  /** Present only on reports created before subjective confidence was removed. */
  confidence: number | null;
  attachment_ids: string[];
}

/**
 * The recommendation that stands, and what the investigation itself had said.
 *
 * When the two differ, `overrides` names the rules that stepped in. Worth showing both: a
 * representative should be able to see that a product was sound on its own evidence and
 * that a rule withheld the payment anyway.
 */
export interface OutcomeDecision {
  recommendation: Recommendation;
  recommended_by_agent: Recommendation;
  overrides: string[];
  explanation: string;
}

/**
 * One damaged item's part of an amount.
 *
 * `unit_price` is what one of these cost on the invoice. What is being paid for the
 * damage is the investigation's judgement and is deliberately not a share of this.
 * Text, like every figure here — a browser number would lose the cents.
 */
export interface AmountComponent {
  product_name: string;
  quantity: number;
  unit_price: string;
  sku: string | null;
}

/**
 * A recommended amount and the whole of its working (FR-2.4).
 *
 * Every figure is text and must stay text: turning one into a browser number is how
 * $100.00 becomes 100.00000000000001. Nothing here is added up on screen either — the
 * arithmetic was done in the service, and doing it again in a browser would be a second
 * calculation that could disagree with the first.
 *
 * The story is in the gaps between three figures. `proposed_usd` is what the investigation
 * judged the damage to be worth. `items_total_usd` is what those items cost on the invoice,
 * which is context and not a limit. `amount_usd` is what is actually recommended — the
 * proposal, unless `cap_applied` says the cap brought it down.
 *
 * `reasoning` is the investigation's own account of why that figure. It is the whole
 * justification for the number now that it is a judgement rather than a sum, so a screen
 * that hides it leaves a representative with nothing to weigh.
 */
export interface AmountDerivation {
  components: AmountComponent[];
  items_total_usd: string;
  proposed_usd: string;
  amount_usd: string;
  cap_usd: string;
  cap_applied: boolean;
  reasoning: string;
  priced_from: string | null;
}

/** Where a report has got to in its review. Approved is final (FR-2.9). */
export type ReportState = "awaiting_review" | "changes_requested" | "approved";

/** Which part of the service produced the thing a representative is looking at. */
export type ReportStage = "screening" | "investigation";

/** An outcome and an amount — what was advised, or what a representative settled on. */
export interface Proposal {
  readonly outcome: Recommendation | null;
  readonly amount_usd: string | null;
}

/** Settled per-product findings. The UI, rather than the backend, lays these fields out. */
export interface InvestigationReportContent {
  readonly kind: "investigation";
  readonly line: ClaimLine;
  readonly context: ClaimContext;
  readonly attachments: readonly Attachment[];
  readonly evidence: readonly EvidenceFinding[];
  readonly assessments: readonly Assessment[];
  readonly outcome: OutcomeDecision;
  readonly amount: AmountDerivation;
  readonly concerns: readonly string[];
  readonly requested_details: readonly string[];
  /** Concise findings; exact merchant asks live in the drafted email instead. */
  readonly finding_summary: string | null;
  readonly corrections_considered: readonly string[];
}

/** Findings for a claim stopped by the deterministic checks. */
export interface ScreeningReportContent {
  readonly kind: "screening";
  readonly context: ClaimContext;
  readonly reasons: readonly TerminalReason[];
  readonly findings: readonly string[];
  readonly gates: readonly GateResult[];
  readonly requires_rep_clarification: boolean;
}

/** Claim-level findings for an unresolved product split. */
export interface ClarificationReportContent {
  readonly kind: "clarification";
  readonly context: ClaimContext;
  readonly attachments: readonly Attachment[];
  readonly candidate_lines: readonly ClaimLine[];
  readonly ambiguity: string;
  readonly concerns: readonly string[];
  readonly requested_details: readonly string[];
}

export type ReportContent =
  | InvestigationReportContent
  | ScreeningReportContent
  | ClarificationReportContent;

export type RepAction = "approved" | "approved_with_override" | "sent_back";

/** One review action, kept as fields rather than appended to a prose document. */
export interface ReportReview {
  readonly review_number: number;
  readonly action: RepAction;
  readonly recommended: Proposal;
  readonly decided: Proposal;
  readonly edited_email: { readonly subject: string; readonly body: string } | null;
  readonly rep_words: string | null;
  readonly over_the_cap_by: string | null;
}

/**
 * One report a representative decides on (FR-2.1).
 *
 * `content` is the canonical report data. The UI constructs its presentation directly from
 * those fields; it never receives or parses a backend-authored prose document.
 *
 * `amount_usd` is **text**, like every other figure the service sends. Nothing here parses it.
 */
export interface Report {
  readonly report_id: string;
  readonly version: number;
  readonly case_id: string;
  readonly claim_line_id: string | null;
  readonly product_name: string | null;
  readonly account_name: string | null;
  readonly user_id: string | null;
  readonly stage: ReportStage;
  readonly state: ReportState;
  readonly recommendation: Recommendation | null;
  readonly amount_usd: string | null;
  readonly confidence: number | null;
  readonly carrier: string | null;
  readonly defect_type: string | null;
  readonly damage_type: string | null;
  readonly order_value_usd: string | null;
  readonly decided: Proposal | null;
  readonly decisions_taken: number;
  readonly drafted_email: DraftedEmail | null;
  readonly content: ReportContent;
  readonly reviews: readonly ReportReview[];
  readonly created_at: string;
}

/** What a representative sends when they approve a report (FR-2.8, action 1). */
export interface Approval {
  readonly outcome?: Recommendation;
  /** Text, never a number — a figure that went through a float is one nobody can trust. */
  readonly amount_usd?: string;
  /** Subject and wording only. The recipient comes from the claim and is not sendable. */
  readonly email?: { readonly subject: string; readonly body: string };
  readonly rep_words?: string;
}
