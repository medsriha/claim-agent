/**
 * The conversation a representative and the agent have had about one report (FR-R.13).
 *
 * Each round is what the representative said and what the agent said back, oldest first,
 * with what it changed and what it deliberately left alone (FR-R.10). Every sentence here
 * comes from the service — the screen adds the labels and nothing else.
 *
 * A round marked as not reworked is one the agent could not answer. Its reply says why, and
 * the findings above it are the ones that were already there. That is shown plainly rather
 * than hidden, because a representative reading an unchanged report needs to know whether it
 * was unchanged on purpose.
 */
import type { RevisionTurn } from "../api/types";
import { PAGE_WORDS } from "../chat/pageWords";

/** Every round so far, or nothing at all for a report that has never been sent back. */
export function RevisionThread({
  revisions,
}: {
  revisions: readonly RevisionTurn[];
}): React.JSX.Element | null {
  if (revisions.length === 0) {
    return null;
  }
  return (
    <section className="revision-thread">
      <h4>The conversation about this report</h4>
      <ol>
        {revisions.map((turn) => (
          <li key={turn.turn} className="revision-turn">
            <Said who="You" words={turn.feedback} />
            <Said who="The agent" words={turn.reply} reworked={turn.reworked} />
            <Listed heading="Changed" items={turn.changed} />
            <Listed heading="Left alone" items={turn.left_unchanged} />
            {turn.needs_reply && (
              <p className="revision-waiting">{PAGE_WORDS.waitingOnYou}</p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * One thing somebody said, labelled with who said it.
 *
 * `reworked` false marks the agent saying it could not rework the report. It is marked
 * rather than hidden, because an unchanged report that failed and an unchanged report that
 * was reviewed and left alone look identical otherwise.
 */
function Said({
  who,
  words,
  reworked = true,
}: {
  who: string;
  words: string;
  reworked?: boolean;
}): React.JSX.Element {
  return (
    <p className={reworked ? "revision-said" : "revision-said is-not-reworked"}>
      <span className="revision-who">{who}</span>
      {words}
    </p>
  );
}

/** A short list under a heading, drawn only when the service sent one. */
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
