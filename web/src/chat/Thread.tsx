/**
 * The conversation about one claim.
 *
 * It draws as many messages as the pacing has counted to, keeps the newest one in view, and
 * offers a way to skip the waiting. It is drawn fresh for each claim — the screen replaces
 * it rather than clearing it — so nothing from the previous claim can survive here.
 */
import { useEffect, useRef } from "react";

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
  const { revealed, showAll, revealing } = useReveal(messages.length);
  const foot = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Keeps the newest message in view as the conversation grows. Harmless when nothing
    // scrolls, and the browser decides whether to animate it.
    foot.current?.scrollIntoView({ block: "end" });
  }, [revealed, working]);

  return (
    <div className="thread">
      <ol className="turns">
        {messages.slice(0, revealed).map((message) => (
          <Message key={message.id} message={message} onRetry={onRetry} />
        ))}
      </ol>

      {working && (
        <p className="working" role="status">
          Screening {caseId}…
        </p>
      )}

      {/* Only offered while there is something left to wait for, so nobody driving a
          demonstration is held up by a timer. */}
      {!working && revealing && (
        <button className="button-secondary show-all" type="button" onClick={showAll}>
          Show all
        </button>
      )}

      <div ref={foot} />
    </div>
  );
}
