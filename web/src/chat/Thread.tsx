/**
 * The conversation about one claim.
 *
 * It draws the messages that have arrived, each either working or settled, and keeps the
 * newest one in view. It is drawn fresh for each claim — the screen replaces it rather than
 * clearing it — so nothing from the previous claim can survive here.
 *
 * There is no way to skip ahead. Watching the work arrive is the point of the screen, and
 * anyone who would rather not watch it is covered by asking their machine for less
 * movement, which settles the whole conversation at once.
 */
import { useEffect, useMemo, useRef } from "react";

import { Message } from "./Message";
import { useReveal } from "./useReveal";
import type { TranscriptMessage } from "./transcript";

interface ThreadProps {
  messages: TranscriptMessage[];
  /** True while the screening is still running and there is nothing yet to report. */
  working: boolean;
  /** The claim being screened, so the waiting message can name it. */
  caseId: string;
  onRetry: () => void;
}

export function Thread({ messages, working, caseId, onRetry }: ThreadProps): React.JSX.Element {
  // Only what the system reports spins. The representative's own line and the screen's own
  // notes are nobody working on anything, so they arrive settled.
  const spins = useMemo(() => messages.map((one) => one.speaker === "system"), [messages]);
  const { stateOf, progress } = useReveal(messages.length, spins);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = scroller.current;
    if (box === null) {
      return;
    }
    // Moved by hand rather than by asking an element to bring itself into view: that would
    // also scroll every scrollable thing around it, and this is the only region on the page
    // that should ever move. Runs on both halves of a message's arrival, because a message
    // settling is what grows it from one line into the whole finding.
    box.scrollTop = box.scrollHeight;
  }, [progress, working]);

  return (
    <div className="thread" ref={scroller}>
      <ol className="turns">
        {messages.map((message, index) => {
          const state = stateOf(index);
          if (state === "hidden") {
            return null;
          }
          return (
            <Message key={message.id} message={message} state={state} onRetry={onRetry} />
          );
        })}
      </ol>

      {working && (
        <p
          className="working"
          role="status"
          aria-label={`Screening ${caseId}. The agent is thinking and the backend is still processing.`}
        >
          <span className="working-wave" aria-hidden="true">
            <span>Screening</span>{" "}
            <span>{caseId}</span>
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </p>
      )}
    </div>
  );
}
