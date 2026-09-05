/**
 * One thing the investigation said while it was working.
 *
 * **This is the only part of the conversation that is not a replay.** Everything else on
 * screen is laid out from an answer that had already arrived; these appear because the
 * service said so, in the order it said it. The sentence is the service's own and is shown
 * unchanged.
 *
 * The kind is used for one thing only — a small mark saying what sort of step it was — and
 * decides nothing. A kind this screen has never heard of still shows its sentence, because
 * the sentence is the part worth reading.
 *
 * The sentence is read as markdown, because what writes it writes markdown: a step is often
 * a list of what the investigation is weighing up, and shown as one line it stops reading as
 * one. Nothing is added or dropped in the reading — see `Markdown.tsx`.
 *
 * The collapsed activity banner says what the agent is doing now. Opening it reveals every
 * event received so far, in stream order, including each event's complete message and
 * structured details.
 */
import { Markdown } from "./Markdown";
import { humanise } from "../display";
import type { RunEventKind } from "../api/types";
import type { ActivityStep } from "../chat/transcript";

interface InvestigationStepProps {
  eventKind: RunEventKind;
  summary: string;
  /** Every event received for this run, in SSE sequence order. */
  history: readonly ActivityStep[];
}

/**
 * The steps worth drawing attention to.
 *
 * `tool_called` is the investigation choosing what to look at next, which is the whole
 * reason this is an agent and not a fixed run of steps. `precedent_gathered` is what
 * comparable claims were decided before. Both are the ones a representative is most likely
 * to stop and read, so they are marked rather than left to look like everything else.
 */
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

/** The first line with anything on it, which is what a shut step shows of itself. */
function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "") ?? "";
}
