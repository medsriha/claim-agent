import { useEffect, useMemo, useRef } from "react";

import { Message } from "./Message";
import { useReveal } from "./useReveal";
import type { TranscriptMessage } from "./transcript";

interface ThreadProps {
  messages: TranscriptMessage[];

  working: boolean;

  caseId: string;
  onRetry: () => void;
}

export function Thread({ messages, working, caseId, onRetry }: ThreadProps): React.JSX.Element {

  const spins = useMemo(() => messages.map((one) => one.speaker === "system"), [messages]);
  const { stateOf, progress } = useReveal(messages.length, spins);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = scroller.current;
    if (box === null) {
      return;
    }

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
