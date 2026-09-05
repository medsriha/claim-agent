/**
 * Turning one screening into an ordered list of things to say.
 *
 * The screen shows a screening as a conversation, so something has to decide what the
 * separate things to say are and what order they come in. That is all this file does.
 *
 * **It arranges; it does not decide.** It never works out a verdict, judges whether a
 * check passed, re-orders the reasons, or touches a figure. Every value it hands on is a
 * value the service sent, in the order the service sent it. This is the file in the whole
 * screen most likely to drift into deciding something, so it is worth keeping dull.
 *
 * The order follows the order the service does the work in: read the claim, the parcel and
 * the order; work out the numbers; run the four checks; reach a verdict; and — only on a
 * stopped claim — write up what was found and draft the email. A reader watching the
 * conversation is watching the real running order, not one of ours.
 */
import type { FailureKind } from "../api/failure";
import type {
  Report,
  Case,
  ClaimContext,
  ClaimInvestigation,
  DraftedEmail,
  GateResult,
  LineInvestigation,
  Order,
  PrecedentSet,
  PreflightResult,
  RunEvent,
  RunEventKind,
  Shipment,
  TerminalReason,
  Verdict,
} from "../api/types";

/**
 * Who a message is from.
 *
 * `page` is kept apart from `system` on purpose: it marks the two sentences the screen
 * wrote itself, so a reader can tell them from everything the service said.
 */
export type MessageSpeaker = "rep" | "system" | "page";

/** What a message holds. The `kind` says which component draws it. */
export type MessageBody =
  | { readonly kind: "picked"; readonly caseId: string }
  | { readonly kind: "claim"; readonly supportCase: Case }
  | { readonly kind: "parcel"; readonly shipment: Shipment | null }
  | { readonly kind: "order"; readonly order: Order | null }
  | { readonly kind: "context"; readonly context: ClaimContext }
  | { readonly kind: "gate"; readonly gate: GateResult }
  | {
      readonly kind: "verdict";
      readonly caseId: string;
      readonly verdict: Verdict;
      readonly reasons: TerminalReason[];
      readonly evaluatedAt: string;
    }
  | { readonly kind: "findings"; readonly findings: string[] }
  | { readonly kind: "email"; readonly email: DraftedEmail }
  | { readonly kind: "escalation" }
  | {
      readonly kind: "precedent";
      /** What the search found. `null` when the request itself never got an answer. */
      readonly found: PrecedentSet | null;
      /** Why nothing could be looked up. `null` when it could be. */
      readonly failureMessage: string | null;
    }
  | {
      /**
       * Something the investigation did, said as it happened.
       *
       * Unlike every other message here, this one arrives while the work is going on
       * rather than being laid out from a finished answer. `summary` is the service's own
       * sentence and is shown unchanged.
       */
      readonly kind: "step";
      readonly eventKind: RunEventKind;
      readonly summary: string;
      readonly detail: Record<string, string>;
    }
  | {
      /** Everything established about one damaged product. */
      readonly kind: "lineReport";
      readonly report: LineInvestigation;
      /** Which of how many, for a heading. Counted by the service's own ordering. */
      readonly position: number;
      readonly outOf: number;
    }
  | {
      /**
       * What the claim came to across all its products.
       *
       * Only the cap can make a claim-level judgement, so this is where it appears. The
       * total is the service's figure, shown as text and never added up here.
       */
      readonly kind: "claimTotal";
      readonly total: string;
      readonly capApplied: boolean;
      readonly concerns: string[];
    }
  | { readonly kind: "report"; readonly report: Report }
  | { readonly kind: "note"; readonly text: string }
  | { readonly kind: "failure"; readonly failure: FailureKind; readonly message: string };

/** One thing to say, and who says it. */
export interface TranscriptMessage {
  /** Stable within a conversation, so drawing it again does not restart its entrance. */
  readonly id: string;
  readonly speaker: MessageSpeaker;
  /**
   * A short heading above the message, or `null` where the body already names itself —
   * a check card carries its own name, and a failure carries its own title.
   */
  readonly label: string | null;
  readonly body: MessageBody;
}

/**
 * The representative's opening line: which claim they picked.
 *
 * Separate from the rest because it is said the moment a claim is chosen, before there is
 * an answer to say anything else about. It carries the id that was picked rather than the
 * one the answer comes back with, so what the representative did is never rewritten
 * underneath them.
 */
export function pickedMessage(caseId: string): TranscriptMessage {
  return { id: "picked", speaker: "rep", label: null, body: { kind: "picked", caseId } };
}

/**
 * What the search for similar past claims came back with.
 *
 * `sought` is the field that matters: it says whether the question was asked at all, which
 * is a different thing from its having been asked and answered with nothing. A stopped
 * claim is never asked about, so nothing about similar claims appears in its conversation.
 */
export interface PrecedentLookup {
  readonly found: PrecedentSet | null;
  readonly failureMessage: string | null;
  readonly sought: boolean;
}

/**
 * Lay a finished screening out as a conversation.
 *
 * @param pickedId - The claim the representative asked for. Used only for their opening
 *   line, so it stays as they typed it.
 * @param result - The answer the service returned, whole. Nothing here is optional: a
 *   screening always carries all four checks and everything that was read, and only a
 *   stopped claim carries a write-up and an email.
 * @param precedent - What the search for similar claims found, and whether it was even
 *   asked. It is asked only on a claim that passed, so `sought` being false is the ordinary
 *   state for a stopped one and means no message about it appears at all.
 * @returns The messages in the order they should appear, opening line first.
 */
export function transcriptFor(
  pickedId: string,
  result: PreflightResult,
  precedent: PrecedentLookup = { found: null, failureMessage: null, sought: false },
): TranscriptMessage[] {
  const messages: TranscriptMessage[] = [pickedMessage(pickedId)];

  messages.push({
    id: "claim",
    speaker: "system",
    label: "Read the claim",
    body: { kind: "claim", supportCase: result.record.case },
  });
  messages.push({
    id: "parcel",
    speaker: "system",
    label: "Read the parcel",
    body: { kind: "parcel", shipment: result.record.shipment },
  });
  messages.push({
    id: "order",
    speaker: "system",
    label: "Read the order",
    body: { kind: "order", order: result.record.order },
  });
  messages.push({
    id: "context",
    speaker: "system",
    label: "The claim in numbers",
    body: { kind: "context", context: result.context },
  });

  // One message per check, so they arrive one at a time. Never sorted: the service fixes
  // this order, and every check is shown whichever way it went — a representative should
  // see the insurance check ran and cleared rather than inferring it from silence.
  result.gates.forEach((gate, index) => {
    messages.push({
      id: `gate-${gate.gate}`,
      speaker: "system",
      // Counted from what actually arrived rather than from the number four, so a
      // screening that ever carries a different number of checks still reads correctly.
      label: `Check ${String(index + 1)} of ${String(result.gates.length)}`,
      body: { kind: "gate", gate },
    });
  });

  // A passing claim moves straight from its checks to the next useful information. Only a
  // stopped claim needs a decision banner calling attention to the terminal outcome.
  if (result.verdict === "terminal") {
    messages.push({
      id: "verdict",
      speaker: "system",
      label: "The decision",
      body: {
        kind: "verdict",
        caseId: result.case_id,
        verdict: result.verdict,
        // Handed on exactly as they arrived. The first reason names the merchant email's
        // subject line, so sorting these would misrepresent which one it leads with.
        reasons: [...result.terminal_reasons],
        evaluatedAt: result.evaluated_at,
      },
    });
  }

  // A stopped claim is owed an explanation, so the service writes one up and drafts the
  // email. A claim that passes carries neither, because there is nothing to explain yet.
  if (result.report === null) {
    // Only a claim that passed is asked about, so this only ever appears here. It comes
    // before the note about the missing stage because it is the one thing on a passing
    // claim a representative can actually use today.
    if (precedent.sought) {
      messages.push({
        id: "precedent",
        speaker: "system",
        label: "Similar claims handled before",
        body: {
          kind: "precedent",
          found: precedent.found,
          failureMessage: precedent.failureMessage,
        },
      });
    }
    return messages;
  }

  messages.push({
    id: "findings",
    speaker: "system",
    label: "What was found",
    body: { kind: "findings", findings: [...result.report.findings] },
  });
  // Two things a stopped claim can end in, and it may end in both. The escalation comes
  // first because being insured leads the reasons: it is what routes the claim out.
  if (result.report.requires_escalation) {
    messages.push({
      id: "escalation",
      speaker: "system",
      label: "Not ours to answer",
      body: { kind: "escalation" },
    });
  }

  // Absent when there is nothing the merchant can be told — a claim stopped only by
  // being insured. The service decides that; the screen just shows what it was given.
  if (result.report.drafted_email !== null) {
    messages.push({
      id: "email",
      speaker: "system",
      label: "Email to the merchant",
      body: { kind: "email", email: result.report.drafted_email },
    });
  }

  return messages;
}

/**
 * Lay a failed screening out as a conversation: the opening line, then what went wrong.
 *
 * Deliberately short. A screening that failed produced no findings, so the conversation
 * shows none — a page that filled in the steps it thinks probably happened would be
 * putting work on screen that nobody did.
 */
export function failureTranscript(
  pickedId: string,
  failure: FailureKind,
  message: string,
): TranscriptMessage[] {
  return [
    pickedMessage(pickedId),
    {
      id: "failure",
      speaker: "system",
      label: null,
      body: { kind: "failure", failure, message },
    },
  ];
}


/**
 * One thing the investigation said, as a message.
 *
 * **This is the only message in the conversation that is not a replay.** Every other one
 * is laid out from an answer that had already arrived; this one is made when the service
 * says it, in the order it said it. The sentence is the service's own and is shown
 * unchanged — the screen adds the heading and nothing else.
 *
 * The heading names the product where the service said which product it was about, so a
 * representative watching two investigations at once can tell them apart.
 *
 * @param event - What the service said.
 * @param labelFor - Turns a claim line id into a product name, where one is known.
 */
export function stepMessage(
  event: RunEvent,
  labelFor: (claimLineId: string) => string | null,
): TranscriptMessage {
  const product = event.claim_line_id === null ? null : labelFor(event.claim_line_id);
  return {
    // The service numbers what it says, so two messages can never share a position and a
    // message redrawn does not restart its entrance.
    id: `step-${String(event.sequence)}`,
    speaker: "system",
    label: product,
    body: {
      kind: "step",
      eventKind: event.kind,
      summary: event.summary,
      detail: event.detail,
    },
  };
}

/**
 * The finished investigation, product by product.
 *
 * Comes after everything the investigation said while it worked, and after the similar
 * claims, because it is the thing a representative decides from and belongs at the end of
 * the reading rather than the middle.
 *
 * A claim whose split was never settled has no products to report on, and says what was
 * unclear instead — nothing may be investigated until somebody has said which products are
 * being claimed for (FR-1a.4).
 *
 * The claim total is shown only where there is more than one product, or where the cap
 * changed the answer. On a single product it would just be that product's figure again.
 */
export function investigationMessages(
  investigation: ClaimInvestigation,
): TranscriptMessage[] {
  if (investigation.triage.ambiguity !== null) {
    return [
      {
        id: "split-unsettled",
        speaker: "system",
        label: "Which product was damaged is unclear",
        // A finding and not a note: the words are the service's own, and a note is drawn
        // with a mark saying the screen wrote it.
        body: { kind: "findings", findings: [investigation.triage.ambiguity] },
      },
    ];
  }

  const messages: TranscriptMessage[] = investigation.lines.map((report, index) => ({
    id: `line-${report.line.claim_line_id}`,
    speaker: "system",
    label: null,
    body: {
      kind: "lineReport",
      report,
      position: index + 1,
      outOf: investigation.lines.length,
    },
  }));

  if (investigation.lines.length > 1 || investigation.claim_cap_applied) {
    messages.push({
      id: "claim-total",
      speaker: "system",
      label: "The claim altogether",
      body: {
        kind: "claimTotal",
        total: investigation.recommended_total_usd,
        capApplied: investigation.claim_cap_applied,
        concerns: [...investigation.claim_concerns],
      },
    });
  }

  // One draft per product that has one, after the reports, so the reading ends on the
  // words that would go to the merchant.
  investigation.lines.forEach((report) => {
    if (report.drafted_email !== null) {
      messages.push({
        id: `line-email-${report.line.claim_line_id}`,
        speaker: "system",
        label: `Email about ${report.line.claimed.name}`,
        body: { kind: "email", email: report.drafted_email },
      });
    }
  });

  return messages;
}

/**
 * One message per report the service kept, in the order it sent them (FR-2.9b).
 *
 * Added at the end of a conversation, because a report is the thing a representative acts on and
 * everything above it is how it was reached. A claim the checks stopped has one; an investigated
 * claim has one per damaged product.
 */
export function reportMessages(reports: readonly Report[]): TranscriptMessage[] {
  return reports.map((report) => ({
    id: `report-${report.report_id}`,
    speaker: "system",
    label: "For your decision",
    body: { kind: "report", report },
  }));
}

/**
 * One sentence the service said, on its own, where a report would otherwise be.
 *
 * Used when the findings arrived and could not be kept: they are on screen above, and this
 * says plainly that there is nothing to approve. The wording is the service's, not ours —
 * only the service knows what failed.
 */
export function noteMessage(text: string): TranscriptMessage {
  return { id: "reports-note", speaker: "system", label: null, body: { kind: "note", text } };
}
