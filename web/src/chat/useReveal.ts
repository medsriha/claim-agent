import { useEffect, useState } from "react";

const WORKING_MS = 850;

const BETWEEN_MS = 300;

export type MessageState = "hidden" | "working" | "settled";

function prefersLessMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

interface Cursor {
  readonly index: number;
  readonly settled: boolean;
}

export interface Replay {

  readonly stateOf: (index: number) => MessageState;

  readonly progress: number;
}

export function useReveal(messageCount: number, spins: readonly boolean[]): Replay {
  const [cursor, setCursor] = useState<Cursor>({ index: 0, settled: false });
  const lessMotion = prefersLessMotion();

  const working = !cursor.settled && (spins[cursor.index] ?? false);

  useEffect(() => {
    if (lessMotion || cursor.index >= messageCount) {
      return undefined;
    }

    const stillWorking = !cursor.settled && (spins[cursor.index] ?? false);
    const timer = window.setTimeout(
      () => {
        setCursor((at) =>
          !at.settled && (spins[at.index] ?? false)
            ? { index: at.index, settled: true }
            : { index: at.index + 1, settled: false },
        );
      },
      stillWorking ? WORKING_MS : BETWEEN_MS,
    );

    return () => {
      window.clearTimeout(timer);
    };
  }, [cursor, messageCount, spins, lessMotion]);

  const stateOf = (index: number): MessageState => {
    if (lessMotion || index < cursor.index) {
      return "settled";
    }
    if (index > cursor.index) {
      return "hidden";
    }
    return working ? "working" : "settled";
  };

  return {
    stateOf,

    progress: lessMotion ? messageCount * 2 : cursor.index * 2 + (working ? 0 : 1),
  };
}
