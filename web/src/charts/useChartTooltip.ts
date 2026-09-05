/**
 * The one way anything on this screen is picked out, by pointer or by keyboard.
 *
 * Every chart shares this so that hovering and focusing produce exactly the same thing: one
 * position is active, and the readout, the tooltip and the marker all come from it. Keyboard
 * parity is not an afterthought here — it is the same state, so the two cannot drift apart.
 *
 * **One focus stop per chart, not one per point.** The arrow keys move along the points. A tab
 * stop for each of fifty-two weeks, across five charts, would be two hundred and sixty stops
 * between the top of the page and the table at the bottom, which is a trap rather than an
 * accommodation.
 *
 * Where the active position came from matters for one thing only: the spoken readout updates on
 * keyboard and not on pointer. A live region driven by every mouse movement is unusable, and a
 * pointer user can already see the tooltip.
 */
import { useCallback, useState } from "react";

/** Which position is picked out, and what picked it. */
export interface Active {
  readonly index: number;
  readonly source: "pointer" | "keyboard";
}

/** What a chart needs to run the shared hover and focus behaviour. */
export interface Tooltip {
  readonly active: Active | null;
  readonly show: (index: number, source: "pointer" | "keyboard") => void;
  readonly clear: () => void;
  readonly onKeyDown: (event: React.KeyboardEvent) => void;
}

/**
 * Track which position of `count` is picked out.
 *
 * @param count - How many positions there are. Zero means nothing can be picked.
 */
export function useChartTooltip(count: number): Tooltip {
  const [active, setActive] = useState<Active | null>(null);

  const show = useCallback((index: number, source: "pointer" | "keyboard"): void => {
    setActive({ index, source });
  }, []);

  const clear = useCallback((): void => {
    setActive(null);
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent): void => {
      if (count === 0) {
        return;
      }
      const at = active?.index ?? 0;
      const step = (to: number): void => {
        event.preventDefault();
        setActive({ index: Math.min(count - 1, Math.max(0, to)), source: "keyboard" });
      };

      if (event.key === "ArrowRight") {
        step(active === null ? 0 : at + 1);
      } else if (event.key === "ArrowLeft") {
        step(active === null ? count - 1 : at - 1);
      } else if (event.key === "Home") {
        step(0);
      } else if (event.key === "End") {
        step(count - 1);
      } else if (event.key === "Escape") {
        setActive(null);
      }
    },
    [active, count],
  );

  return { active, show, clear, onKeyDown };
}
