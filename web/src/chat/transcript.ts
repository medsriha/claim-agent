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
 * The order follows the deterministic screening: read the claim, parcel, and order; work out
 * the numbers; run the four checks; then show the canonical report returned by investigation.
 */
import type { FailureKind } from "../api/failure";
import type {
  Report,
  Case,
  ClaimContext,
  GateResult,
  Order,
  PrecedentSet,
  PreflightResult,
  RunEvent,
  RunEventKind,
  Shipment,
} from "../api/types";

/**
 * Who a message is from.
 *
 * `page` is kept apart from `system` on purpose: it marks the two sentences the screen
 * wrote itself, so a reader can tell them from everything the service said.
 */
export type MessageSpeaker = "rep" | "system" | "page";

/** One event retained inside the expandable live activity log. */
export interface ActivityStep {
  readonly sequence: number;
  readonly eventKind: RunEventKind;
  readonly summary: string;
  readonly detail: Record<string, string>;
  readonly label: string | null;
}

/** What a message holds. The `kind` says which component draws it. */
export type MessageBody =
  | { readonly kind: "picked"; readonly caseId: string }
  | { readonly kind: "claim"; readonly supportCase: Case }
  | { readonly kind: "parcel"; readonly shipment: Shipment | null }
  | { readonly kind: "order"; readonly order: Order | null }
  | { readonly kind: "context"; readonly context: ClaimContext }
  | { readonly kind: "gate"; readonly gate: GateResult }
  | { readonly kind: "findings"; readonly findings: string[] }
  | {
      /** The live SSE activity bar: latest action outside, complete history inside. */
      readonly kind: "step";
      readonly eventKind: RunEventKind;
      readonly summary: string;
      readonly detail: Record<string, string>;
      readonly history: readonly ActivityStep[];
    }
  | {
      readonly kind: "precedent";
      /** What the search found. `null` when the request itself never got an answer. */
      readonly found: PrecedentSet | null;
      /** Why nothing could be looked up. `null` when it could be. */
      readonly failureMessage: string | null;
    }
  | {
      readonly kind: "report";
      readonly report: Report;
      readonly unavailableReason: string | null;
    }
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

  // The report is fetched through the investigation endpoint for both outcomes, so the
  // screening transcript does not render a second findings or email surface here.
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

/** Turn one live SSE event into the activity panel the next event will update. */
export function stepMessage(
  event: RunEvent,
  labelFor: (claimLineId: string) => string | null,
): TranscriptMessage {
  const product = event.claim_line_id === null ? null : labelFor(event.claim_line_id);
  const step: ActivityStep = {
    sequence: event.sequence,
    eventKind: event.kind,
    summary: event.summary,
    detail: event.detail,
    label: product,
  };
  return {
    // The activity bar is one persistent message. A stable key keeps it open while later
    // SSE events extend its log instead of remounting and collapsing it.
    id: "activity",
    speaker: "system",
    label: product,
    body: {
      kind: "step",
      eventKind: event.kind,
      summary: event.summary,
      detail: event.detail,
      history: [step],
    },
  };
}


/**
 * One message per canonical report the service sent, in its original order (FR-2.9b).
 *
 * A claim the checks stopped has one; an investigated claim has one per damaged product.
 */
export function reportMessages(
  reports: readonly Report[],
  unavailableReason: string | null,
): TranscriptMessage[] {
  if (reports.length === 0) {
    return [
      noteMessage(
        unavailableReason ?? "The investigation did not produce a report to review.",
      ),
    ];
  }
  return reports.map((report) => ({
    id: `report-${report.report_id}`,
    speaker: "system",
    label: "For your decision",
    body: { kind: "report", report, unavailableReason },
  }));
}

/**
 * One sentence where a report would otherwise be, used when none was produced.
 */
export function noteMessage(text: string): TranscriptMessage {
  return { id: "reports-note", speaker: "system", label: null, body: { kind: "note", text } };
}
