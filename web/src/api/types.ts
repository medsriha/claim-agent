export type Verdict = "proceed" | "terminal";

export type GateName = "age" | "claim_type" | "key_information" | "insurance";

export type TerminalReason =
  | "shipment_insured"
  | "claim_too_old"
  | "wrong_claim_type"
  | "missing_key_information";

export interface GateResult {
  gate: GateName;
  passed: boolean;
  reason: TerminalReason | null;
  explanation: string;
  observed: Record<string, string>;
}

export interface OrderLineItem {
  product_id: string | null;
  name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
}

export interface Order {
  order_id: string;
  user_id: string | null;
  line_items: OrderLineItem[];
  created_date: string | null;
}

export interface Shipment {
  shipment_id: string;
  is_insured: boolean;
  order_id: string | null;
  carrier: string | null;
  tracking_number: string | null;
  status: string | null;
  delivered_date: string | null;
}

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

export interface CaseRecord {
  case: Case;
  shipment: Shipment | null;
  order: Order | null;
}

export interface Attachment {
  attachment_id: string;
  url: string;
  file_name: string | null;
  content_type: string | null;
}

export interface MerchantCorrection {
  user_id: string;
  case_id: string;
  summary: string;
  recorded_at: string;
}

export interface ClaimContext {
  order_value_usd: string | null;
  is_high_value: boolean;
  days_since_delivery: number | null;
  delivered_date: string | null;
  merchant_corrections: MerchantCorrection[];
}

export interface DraftedEmail {
  to: string | null;
  subject: string;
  body: string;
  is_draft: true;
}

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

export type MatchOutcome = "matched" | "not_on_order" | "ambiguous";

export type Recommendation =
  | "approve"
  | "approve_high_value"
  | "request_info"
  | "request_rep_clarification";

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

export interface PrecedentSimilarity {
  score: number;
  reasons: string[];
}

export interface RetrievedPrecedent {
  record: PrecedentRecord;
  similarity: PrecedentSimilarity;
}

export interface PrecedentSet {
  retrieved: RetrievedPrecedent[];
  considered: number;
  unavailable_reason: string | null;
  was_read: boolean;
}

export type RunEventKind =
  | "screened"
  | "attachments_listed"
  | "image_classified"
  | "evidence_settled"
  | "claim_split"
  | "precedent_gathered"
  | "investigation_started"
  | "tool_called"
  | "thinking"
  | "investigation_finished"
  | "revision_started"
  | "report_ready"
  | "failed";

export interface RunEvent {
  sequence: number;
  kind: RunEventKind;
  summary: string;
  detail: Record<string, string>;
}

export interface ClaimLine {
  claim_line_id: string;
  claimed: { name: string; quantity: number; sku: string | null };
  match: "matched" | "not_on_order" | "ambiguous";
  order_line: OrderLineItem | null;
  candidate_order_lines: OrderLineItem[];
  damage_attachment_ids: string[];
}

export interface EvidenceFinding {
  kind: "invoice" | "customer_confirmation" | "damaged_product_photo" | "outer_packaging_photo";
  state: "present" | "missing" | "unusable" | "unreadable";
  observed: string;
  attachment_id: string | null;
  problem: string | null;
}

export interface Assessment {
  name:
    | "damage_visible"
    | "product_identifiable"
    | "product_on_invoice"
    | "packaging_documented";
  passed: boolean;
  reasoning: string;

  confidence: number | null;
  attachment_ids: string[];
}

export interface OutcomeDecision {
  recommendation: Recommendation;
  recommended_by_agent: Recommendation;
  overrides: string[];
  explanation: string;
}

export interface AmountComponent {
  product_name: string;
  quantity: number;
  unit_price: string;
  sku: string | null;
}

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

export type ReportState = "awaiting_review" | "changes_requested" | "approved";

export type ReportStage = "screening" | "investigation";

export interface Proposal {
  readonly outcome: Recommendation | null;
  readonly amount_usd: string | null;
}

export interface InvestigationReportContent {
  readonly kind: "investigation";
  readonly lines: readonly ClaimLine[];
  readonly context: ClaimContext;
  readonly attachments: readonly Attachment[];
  readonly evidence: readonly EvidenceFinding[];
  readonly assessments: readonly Assessment[];
  readonly outcome: OutcomeDecision;
  readonly amount: AmountDerivation;
  readonly concerns: readonly string[];
  readonly requested_details: readonly string[];

  readonly finding_summary: string | null;
  readonly corrections_considered: readonly string[];
}

export interface ScreeningReportContent {
  readonly kind: "screening";
  readonly context: ClaimContext;
  readonly reasons: readonly TerminalReason[];
  readonly findings: readonly string[];
  readonly gates: readonly GateResult[];
  readonly requires_rep_clarification: boolean;
}

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

export interface ReportReview {
  readonly review_number: number;
  readonly action: RepAction;
  readonly recommended: Proposal;
  readonly decided: Proposal;
  readonly edited_email: { readonly subject: string; readonly body: string } | null;
  readonly rep_words: string | null;
  readonly over_the_cap_by: string | null;
}

export interface RevisionTurn {
  readonly turn: number;
  readonly from_version: number;
  readonly feedback: string;
  readonly reply: string;
  readonly changed: readonly string[];
  readonly left_unchanged: readonly string[];
  readonly needs_reply: boolean;
  readonly reworked: boolean;
  readonly reinvestigated: boolean;
}

export interface Report {
  readonly report_id: string;
  readonly version: number;
  readonly case_id: string;

  readonly product_names: readonly string[];
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
  readonly revisions: readonly RevisionTurn[];
  readonly created_at: string;
}

export interface Approval {
  readonly outcome?: Recommendation;

  readonly amount_usd?: string;

  readonly email?: { readonly subject: string; readonly body: string };
  readonly rep_words?: string;
}

export interface ClaimView {
  readonly case_id: string;
  readonly reports: readonly Report[];
}
