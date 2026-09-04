/**
 * Letting a conversation appear one message at a time.
 *
 * Given how many messages there are, this counts up to that number with a pause between
 * each, and the screen draws only as many as it has counted to. Messages added while it is
 * still counting — which is what happens when the answer arrives after the representative's
 * opening line — are picked up without restarting.
 *
 * **The pauses measure nothing.** They exist so a reader can take in one message before the
 * next arrives. Nothing here knows or reports how long any part of the screening took.
 */
import { useCallback, useEffect, useState } from "react";

/**
 * How long to wait between messages, in milliseconds.
 *
 * Long enough to read a heading and see where the next message lands, short enough that a
 * ten-message conversation does not outlast anyone's patience. It lives here rather than in
 * the theme file because a timer needs a number and a stylesheet cannot hand one over; the
 * entrance the messages fade in with is the part that is styled.
 */
const PAUSE_BETWEEN_MESSAGES_MS = 420;

/**
 * True when this machine asks for less movement.
 *
 * Read once. Somebody changing the setting mid-session keeps the pacing they started with,
 * which is a small enough wrong to accept for a demonstration.
 */
function prefersLessMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export interface Reveal {
  /** How many messages to draw, counting from the start of the list. */
  readonly revealed: number;
  /** Draw the rest at once. Safe to call when there is nothing left to draw. */
  readonly showAll: () => void;
  /** True while messages are still arriving, so the screen can offer to skip ahead. */
  readonly revealing: boolean;
}

/**
 * Count up to `messageCount`, one message at a time.
 *
 * A machine set to reduce motion is given everything at once and no timer ever starts.
 *
 * @param messageCount - How many messages the conversation holds now. May grow between
 *   renders; the count carries on from where it was rather than starting again.
 */
export function useReveal(messageCount: number): Reveal {
  // Everything at once for anyone who asked for less movement, so the timer below is never
  // the reason they are waiting.
  const [revealed, setRevealed] = useState(() => (prefersLessMotion() ? messageCount : 0));

  useEffect(() => {
    if (revealed >= messageCount) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setRevealed((shown) => shown + 1);
    }, PAUSE_BETWEEN_MESSAGES_MS);
    // Cleared on the way out, so a conversation replaced mid-count leaves no timer behind
    // to add a message to a claim nobody is looking at any more.
    return () => {
      window.clearTimeout(timer);
    };
  }, [revealed, messageCount]);

  const showAll = useCallback((): void => {
    setRevealed(messageCount);
  }, [messageCount]);

  return { revealed: Math.min(revealed, messageCount), showAll, revealing: revealed < messageCount };
}
