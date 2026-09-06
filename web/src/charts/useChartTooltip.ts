import { useCallback, useState } from "react";

export interface Active {
  readonly index: number;
  readonly source: "pointer" | "keyboard";
}

export interface Tooltip {
  readonly active: Active | null;
  readonly show: (index: number, source: "pointer" | "keyboard") => void;
  readonly clear: () => void;
  readonly onKeyDown: (event: React.KeyboardEvent) => void;
}

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
