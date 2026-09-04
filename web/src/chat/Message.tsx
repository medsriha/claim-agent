/**
 * One message in the conversation: who it is from, what it is called, and its contents.
 *
 * This is the only place that knows which component draws which kind of message. It holds
 * no rules of its own — every value it passes on came from the service, and the labels it
 * draws were settled when the conversation was laid out.
 */
import { EmailComposer } from "./EmailComposer";
import { EscalationAction } from "./EscalationAction";
import type { MessageState } from "./useReveal";
import { ClaimRead, OrderRead, ParcelRead } from "../components/CaseReads";
import { ClaimNumbers } from "../components/ClaimNumbers";
import { ClaimTotal } from "../components/ClaimTotal";
import { EvaluatedAt, Findings } from "../components/Findings";
import { FailureNotice } from "../components/FailureNotice";
import { GateCard } from "../components/GateCard";
import { InvestigationStep } from "../components/InvestigationStep";
import { LineReport } from "../components/LineReport";
import { SimilarClaims } from "../components/SimilarClaims";
import { Spinner } from "../components/Spinner";
import { VerdictBanner } from "../components/VerdictBanner";
import type { TranscriptMessage } from "./transcript";

interface MessageProps {
  message: TranscriptMessage;
  /** Whether this message is still working or has settled into its finding. */
  state: MessageState;
  /** Screen the same claim again. Only ever reached from a failure. */
  onRetry: () => void;
}

export function Message({ message, state, onRetry }: MessageProps): React.JSX.Element {
  return (
    // Named outright rather than built from the speaker, so the one class that carries a
    // style is greppable and no class name is invented that the stylesheet has no rule for.
    <li className={message.speaker === "rep" ? "turn turn-rep" : "turn"}>
      {message.label !== null && <p className="turn-label">{message.label}</p>}
      <div className="turn-body">
        <Body message={message} state={state} onRetry={onRetry} />
      </div>
    </li>
  );
}

/**
 * What a message that is still working looks like: something turning, and a word for it.
 *
 * A check draws its own working state instead, because it already has a place for a mark
 * and turning it into a spinner is what makes the mark's arrival read as an answer.
 */
function Working(): React.JSX.Element {
  return (
    <p className="bubble bubble-working">
      <Spinner />
      <span className="working-word">Working…</span>
    </p>
  );
}

/**
 * The contents of one message.
 *
 * A `switch` over every kind, with no fallback branch: adding a kind without drawing it
 * becomes a type error here rather than a blank space on screen.
 */
function Body({ message, state, onRetry }: MessageProps): React.JSX.Element {
  const { body } = message;
  const working = state === "working";

  // A check keeps its own frame while it works, so the spinner sits exactly where the tick
  // or cross will be. Everything else stands behind one plain working message.
  if (working && body.kind !== "gate") {
    return <Working />;
  }

  switch (body.kind) {
    case "picked":
      return <p className="bubble bubble-rep">Screen {body.caseId}</p>;

    case "claim":
      return (
        <div className="bubble">
          <ClaimRead supportCase={body.supportCase} />
        </div>
      );

    case "parcel":
      return (
        <div className="bubble">
          <ParcelRead shipment={body.shipment} />
        </div>
      );

    case "order":
      return (
        <div className="bubble">
          <OrderRead order={body.order} />
        </div>
      );

    case "context":
      return (
        <div className="bubble">
          <ClaimNumbers context={body.context} />
        </div>
      );

    case "gate":
      // No bubble around it: a check card carries its own frame and its own colour down
      // the edge, and nesting that inside another box reads as two things, not one.
      return <GateCard gate={body.gate} working={working} />;

    case "verdict":
      return (
        <>
          <VerdictBanner caseId={body.caseId} verdict={body.verdict} reasons={body.reasons} />
          <EvaluatedAt moment={body.evaluatedAt} />
        </>
      );

    case "findings":
      return (
        <div className="bubble">
          <Findings findings={body.findings} />
        </div>
      );

    case "email":
      return (
        <div className="bubble">
          <EmailComposer email={body.email} />
        </div>
      );

    case "escalation":
      return (
        <div className="bubble">
          <EscalationAction />
        </div>
      );

    case "precedent":
      return (
        <div className="bubble">
          <SimilarClaims found={body.found} failureMessage={body.failureMessage} />
        </div>
      );

    case "note":
      return (
        <p className="note">
          <span className="note-mark">This screen, not the system</span>
          {body.text}
        </p>
      );

    case "step":
      // No bubble: a step is a line of narration rather than a finding, and boxing it
      // would give it the same weight as the report it is leading up to.
      return (
        <InvestigationStep
          eventKind={body.eventKind}
          summary={body.summary}
          detail={body.detail}
        />
      );

    case "lineReport":
      // Carries its own frame and its own colour down the edge, like a check card.
      return <LineReport report={body.report} position={body.position} outOf={body.outOf} />;

    case "claimTotal":
      return (
        <div className="bubble">
          <ClaimTotal
            total={body.total}
            capApplied={body.capApplied}
            concerns={body.concerns}
          />
        </div>
      );

    case "failure":
      return <FailureNotice kind={body.failure} message={body.message} onRetry={onRetry} />;
  }
}
