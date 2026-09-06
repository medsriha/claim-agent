import type { RevisionTurn } from "../api/types";
import { PAGE_WORDS } from "../chat/pageWords";

export function RevisionThread({
  revisions,
}: {
  revisions: readonly RevisionTurn[];
}): React.JSX.Element | null {
  if (revisions.length === 0) {
    return null;
  }
  return (
    <section className="revision-thread" aria-label="Conversation about this report">
      {revisions.map((turn) => (
        <div key={turn.turn} className="revision-round">
          <p className="revision-bubble is-rep">{turn.feedback}</p>
          <div
            className={
              turn.reworked
                ? "revision-bubble is-agent"
                : "revision-bubble is-agent is-unchanged"
            }
          >
            <p className="revision-reply">{turn.reply}</p>
            <Listed heading="Changed" items={turn.changed} />
            <Listed heading="Left alone" items={turn.left_unchanged} />
            {turn.reinvestigated && (
              <p className="revision-aside">{PAGE_WORDS.investigatedAgain}</p>
            )}
            {turn.needs_reply && <p className="revision-aside">{PAGE_WORDS.waitingOnYou}</p>}
          </div>
        </div>
      ))}
    </section>
  );
}

function Listed({
  heading,
  items,
}: {
  heading: string;
  items: readonly string[];
}): React.JSX.Element | null {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="revision-list">
      <span className="revision-list-heading">{heading}</span>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
