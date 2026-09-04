/**
 * Letting a conversation arrive the way work arrives: one message at a time, each of them
 * busy for a moment before it says what it found.
 *
 * Every message the system sends goes through two phases. It appears **working** — its
 * heading with something spinning where its answer will be — and then it **settles** into
 * the finding itself. A check therefore spins and then shows a tick or a cross, which is
 * what makes the conversation read as work being done rather than a page being filled in.
 *
 * **None of this measures anything.** The screening has already finished by the time the
 * first message appears; the whole answer arrived in one reply. The spinning is a reading
 * aid, not a report of how long a step took, and nothing here knows how long anything took.
 * That is a deliberate illusion and the screen says as much in the places a reader will
 * look — see the design notes. It is worth knowing before you trust the rhythm of it.
 */
import { useEffect, useState } from "react";

/**
 * How long a message spins before it settles, in milliseconds.
 *
 * Long enough to register as work happening and to read the heading while it does.
 */
const WORKING_MS = 850;

/** How long to wait after a message settles before the next one appears. */
const BETWEEN_MS = 300;

/** Whether a message is not here yet, busy, or done. */
export type MessageState = "hidden" | "working" | "settled";

/**
 * True when this machine asks for less movement.
 *
 * Read on every render rather than stored, which keeps it out of the state and means no
 * timer has to be cancelled when it changes.
 */
function prefersLessMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Where the replay has got to: which message is arriving, and whether it is still busy. */
interface Cursor {
  readonly index: number;
  readonly working: boolean;
}

export interface Replay {
  /** What to draw for the message at this position. */
  readonly stateOf: (index: number) => MessageState;
  /**
   * How many messages have appeared so far, busy ones included. Changes as the replay
   * advances, which is what the screen watches to keep the newest message in view.
   */
  readonly arrived: number;
}

/**
 * Play a conversation out, message by message.
 *
 * Messages added while it is still playing — which is what happens when the answer arrives
 * after the representative's opening line — are picked up without starting again.
 *
 * A machine set to reduce movement is given everything settled at once, and no timer is
 * ever started. There is no button to skip ahead: watching the work is the point of the
 * screen, and anyone who does not want to watch it is covered by that setting.
 *
 * @param messageCount - How many messages the conversation holds now. May grow.
 * @param spins - Per message, whether it should spin before it settles. The
 *   representative's own line and the screen's own notes appear settled straight away:
 *   neither is the system working on anything.
 */
export function useReveal(messageCount: number, spins: readonly boolean[]): Replay {
  const [cursor, setCursor] = useState<Cursor>(() => ({
    index: 0,
    working: spins[0] ?? false,
  }));
  const lessMotion = prefersLessMotion();

  useEffect(() => {
    if (lessMotion || cursor.index >= messageCount) {
      return undefined;
    }

    const settleThisOne = cursor.working;
    const timer = window.setTimeout(
      () => {
        setCursor((at) =>
          at.working
            ? { index: at.index, working: false }
            : { index: at.index + 1, working: spins[at.index + 1] ?? false },
        );
      },
      settleThisOne ? WORKING_MS : BETWEEN_MS,
    );

    // Cleared on the way out, so a conversation replaced part-way through leaves no timer
    // behind to advance a claim nobody is looking at any more.
    return () => {
      window.clearTimeout(timer);
    };
  }, [cursor, messageCount, spins, lessMotion]);

  const stateOf = (index: number): MessageState => {
    if (lessMotion) {
      return "settled";
    }
    if (index < cursor.index) {
      return "settled";
    }
    if (index > cursor.index) {
      return "hidden";
    }
    return cursor.working ? "working" : "settled";
  };

  return {
    stateOf,
    arrived: lessMotion ? messageCount : Math.min(cursor.index + 1, messageCount),
  };
}
