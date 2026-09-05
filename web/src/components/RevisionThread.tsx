/**
 * The conversation between a representative and the agent about one report (FR-R.13).
 *
 * Drawn as a chat, because that is what it is: the representative types something, the agent
 * answers, and it goes round as many times as they like. Their messages sit on the right,
 * the agent's on the left, oldest first.
 *
 * Every sentence in it comes from the service. The screen adds who said what and nothing
 * else — it never summarises a round, reorders one, or offers an opinion on whether the
 * answer was any good.
 *
 * What the agent changed and what it left alone hang under its message as a short aside,
 * because they are supporting detail for a reply rather than the reply itself.
 */
import type { RevisionTurn } from "../api/types";
import { PAGE_WORDS } from "../chat/pageWords";

/** Every round so far, or nothing at all for a report nobody has written back about. */
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

/** A short list under the agent's message, drawn only when the service sent one. */
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
