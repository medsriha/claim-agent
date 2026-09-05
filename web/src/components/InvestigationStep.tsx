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
 * Every step is a collapsed activity banner. Its first line says what the agent is doing
 * now; opening it reveals the complete message and its structured details. The stream
 * replaces this component for every new action, so each new action starts collapsed.
 */
import { Markdown } from "./Markdown";
import { humanise } from "../display";
import type { RunEventKind } from "../api/types";

interface InvestigationStepProps {
  eventKind: RunEventKind;
  summary: string;
  /** The same facts in named parts. Shown only where there is something to show. */
  detail: Record<string, string>;
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
  detail,
}: InvestigationStepProps): React.JSX.Element {
  const shown = Object.entries(detail).filter(([, value]) => value !== "");
  const noticeable = WORTH_NOTICING.has(eventKind);

  return (
    <details className={noticeable ? "step step-noticed" : "step"}>
      <summary className="step-summary">
        <span className="step-kind">{humanise(eventKind)}</span>
        <span className="step-peek">{firstLine(summary)}</span>
      </summary>

      <div className="step-content">
        <Markdown text={summary} className="step-wrote" />

        {shown.length > 0 && (
          <dl className="step-detail">
            {shown.map(([key, value]) => (
              <div key={key} className="step-detail-row">
                <dt className="step-detail-key">{humanise(key)}</dt>
                <dd className="step-detail-value">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </details>
  );
}

/** The first line with anything on it, which is what a shut step shows of itself. */
function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "") ?? "";
}
