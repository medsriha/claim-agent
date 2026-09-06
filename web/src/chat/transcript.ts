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

export type MessageSpeaker = "rep" | "system" | "page";

export interface ActivityStep {
  readonly sequence: number;
  readonly eventKind: RunEventKind;
  readonly summary: string;
  readonly detail: Record<string, string>;
  readonly label: string | null;
}

export type MessageBody =
  | { readonly kind: "picked"; readonly caseId: string }
  | { readonly kind: "claim"; readonly supportCase: Case }
  | { readonly kind: "parcel"; readonly shipment: Shipment | null }
  | { readonly kind: "order"; readonly order: Order | null }
  | { readonly kind: "context"; readonly context: ClaimContext }
  | { readonly kind: "gate"; readonly gate: GateResult }
  | { readonly kind: "findings"; readonly findings: string[] }
  | {

      readonly kind: "step";
      readonly eventKind: RunEventKind;
      readonly summary: string;
      readonly detail: Record<string, string>;
      readonly history: readonly ActivityStep[];
    }
  | {
      readonly kind: "precedent";

      readonly found: PrecedentSet | null;

      readonly failureMessage: string | null;
    }
  | {
      readonly kind: "report";
      readonly report: Report;
      readonly unavailableReason: string | null;
    }
  | { readonly kind: "note"; readonly text: string }
  | { readonly kind: "failure"; readonly failure: FailureKind; readonly message: string };

export interface TranscriptMessage {

  readonly id: string;
  readonly speaker: MessageSpeaker;

  readonly label: string | null;
  readonly body: MessageBody;
}

export function pickedMessage(caseId: string): TranscriptMessage {
  return { id: "picked", speaker: "rep", label: null, body: { kind: "picked", caseId } };
}

export interface PrecedentLookup {
  readonly found: PrecedentSet | null;
  readonly failureMessage: string | null;
  readonly sought: boolean;
}

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
        label: "Similar claims",
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
export function stepMessage(event: RunEvent): TranscriptMessage {
  const step: ActivityStep = {
    sequence: event.sequence,
    eventKind: event.kind,
    summary: event.summary,
    detail: event.detail,
    label: null,
  };
  return {
    // The activity bar is one persistent message. A stable key keeps it open while later
    // SSE events extend its log instead of remounting and collapsing it.
    id: "activity",
    speaker: "system",
    label: null,
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
 * The claim's report, as the one message a representative decides from (FR-2.9b).
 *
 * One claim is one report, whether the checks stopped it or the investigation looked into
 * every product on it.
 */
export function reportMessages(
  report: Report | null,
  unavailableReason: string | null,
): TranscriptMessage[] {
  if (report === null) {
    return [
      noteMessage(
        unavailableReason ?? "The investigation did not produce a report to review.",
      ),
    ];
  }
  return [
    {
      id: `report-${report.report_id}`,
      speaker: "system",
      label: "For your decision",
      body: { kind: "report", report, unavailableReason },
    },
  ];
}

/**
 * One sentence where a report would otherwise be, used when none was produced.
 */
export function noteMessage(text: string): TranscriptMessage {
  return { id: "reports-note", speaker: "system", label: null, body: { kind: "note", text } };
}
