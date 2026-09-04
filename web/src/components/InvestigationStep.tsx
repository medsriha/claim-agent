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
 * **A step that runs long is folded away rather than shown whole.** The investigation's own
 * reasoning and a tool that answers at length are both far longer than a line of narration,
 * and one of them unfolded fills the screen and pushes the report it leads up to out of
 * sight. A long step is shown quieter than the rest, inside a box that scrolls rather than
 * grows, and a representative can shut it or open it as they please.
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

/** How much a step may say before it is folded away instead of shown outright. */
const LONGEST_SHOWN_OUTRIGHT_CHARACTERS = 240;

/** How many lines a step may run to before the same applies. */
const LONGEST_SHOWN_OUTRIGHT_LINES = 3;

export function InvestigationStep({
  eventKind,
  summary,
  detail,
}: InvestigationStepProps): React.JSX.Element {
  const shown = Object.entries(detail).filter(([, value]) => value !== "");
  const noticeable = WORTH_NOTICING.has(eventKind);

  return (
    <div className={noticeable ? "step step-noticed" : "step"}>
      {runsLong(summary) ? (
        // Open to begin with: watching the work happen is the reason any of this is on
        // screen, and a step that arrived already shut would put the stream back to being
        // something a representative has to go looking through.
        <details className="step-fold" open>
          <summary className="step-fold-summary">
            <span className="step-kind">{humanise(eventKind)}</span>
            {/* Only ever seen while the step is shut, so somebody can tell what they are
                opening without opening it. Shown as it was written, markdown marks and
                all — this is the service's own line, not a description of it. */}
            <span className="step-peek">{firstLine(summary)}</span>
          </summary>
          <Markdown text={summary} className="step-wrote" />
        </details>
      ) : (
        <div className="step-summary">
          <span className="step-kind">{humanise(eventKind)}</span>
          <Markdown text={summary} className="step-said" />
        </div>
      )}

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
  );
}

/**
 * Whether a step says enough to be worth folding away.
 *
 * Judged on how much there is to read rather than on what sort of step it is. Most steps
 * are one short sentence and read best as a line of narration, whatever their kind; the
 * ones that run long are usually the investigation reasoning aloud or a tool answering at
 * length, but a kind this screen has never heard of gets the same treatment on the same
 * terms, and a short remark is never boxed up for nothing.
 */
function runsLong(text: string): boolean {
  return (
    text.length > LONGEST_SHOWN_OUTRIGHT_CHARACTERS ||
    text.split("\n").length > LONGEST_SHOWN_OUTRIGHT_LINES
  );
}

/** The first line with anything on it, which is what a shut step shows of itself. */
function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "") ?? "";
}
