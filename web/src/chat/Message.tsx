import type { MessageState } from "./useReveal";
import { ClaimRead, OrderRead, ParcelRead } from "../components/CaseReads";
import { ClaimNumbers } from "../components/ClaimNumbers";
import { Findings } from "../components/Findings";
import { FailureNotice } from "../components/FailureNotice";
import { GateCard } from "../components/GateCard";
import { InvestigationStep } from "../components/InvestigationStep";
import { ReportCard } from "../components/ReportCard";
import { SimilarClaims } from "../components/SimilarClaims";
import { Spinner } from "../components/Spinner";
import type { TranscriptMessage } from "./transcript";

interface MessageProps {
  message: TranscriptMessage;

  state: MessageState;

  onRetry: () => void;
}

export function Message({ message, state, onRetry }: MessageProps): React.JSX.Element {
  return (

    <li className={message.speaker === "rep" ? "turn turn-rep" : "turn"}>
      {message.label !== null && <p className="turn-label">{message.label}</p>}
      <div className="turn-body">
        <Body message={message} state={state} onRetry={onRetry} />
      </div>
    </li>
  );
}

function Working(): React.JSX.Element {
  return (
    <p className="bubble bubble-working">
      <Spinner />
      <span className="working-word">Working…</span>
    </p>
  );
}

function Body({ message, state, onRetry }: MessageProps): React.JSX.Element {
  const { body } = message;
  const working = state === "working";

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

      return <GateCard gate={body.gate} working={working} />;

    case "findings":
      return (
        <div className="bubble">
          <Findings findings={body.findings} />
        </div>
      );

    case "step":
      return (
        <InvestigationStep
          eventKind={body.eventKind}
          summary={body.summary}
          history={body.history}
        />
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

    case "report":

      return <ReportCard report={body.report} unavailableReason={body.unavailableReason} />;

    case "failure":
      return <FailureNotice kind={body.failure} message={body.message} onRetry={onRetry} />;
  }
}
