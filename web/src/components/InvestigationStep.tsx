import { Markdown } from "./Markdown";
import { humanise } from "../display";
import type { RunEventKind } from "../api/types";
import type { ActivityStep } from "../chat/transcript";

interface InvestigationStepProps {
  eventKind: RunEventKind;
  summary: string;

  history: readonly ActivityStep[];
}

const WORTH_NOTICING: ReadonlySet<string> = new Set(["tool_called", "precedent_gathered"]);

export function InvestigationStep({
  eventKind,
  summary,
  history,
}: InvestigationStepProps): React.JSX.Element {
  const noticeable = WORTH_NOTICING.has(eventKind);

  return (
    <details className={noticeable ? "step step-noticed" : "step"}>
      <summary className="step-summary">
        <span className="step-kind">{humanise(eventKind)}</span>
        <span className="step-peek">{firstLine(summary)}</span>
        <span className="step-count">
          {history.length} {history.length === 1 ? "step" : "steps"}
        </span>
      </summary>

      <div className="step-content">
        <ol className="step-history" aria-label="Agent activity log">
          {history.map((step) => (
            <li className="step-history-entry" key={step.sequence}>
              <div className="step-history-heading">
                <span className="step-kind">{humanise(step.eventKind)}</span>
                {step.label !== null && <span className="step-line-label">{step.label}</span>}
              </div>
              <Markdown text={step.summary} className="step-wrote" />
              <StepDetail detail={step.detail} />
            </li>
          ))}
        </ol>
      </div>
    </details>
  );
}

function StepDetail({ detail }: { detail: Record<string, string> }): React.JSX.Element | null {
  const shown = Object.entries(detail).filter(([, value]) => value !== "");
  if (shown.length === 0) {
    return null;
  }
  return (
    <dl className="step-detail">
      {shown.map(([key, value]) => (
        <div key={key} className="step-detail-row">
          <dt className="step-detail-key">{humanise(key)}</dt>
          <dd className="step-detail-value">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "") ?? "";
}
