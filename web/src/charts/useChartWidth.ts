import { useEffect, useRef, useState } from "react";

export function useChartWidth(): {
  box: React.RefObject<HTMLDivElement | null>;
  width: number;
} {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = box.current;
    if (element === null) {
      return;
    }

    setWidth(element.clientWidth);

    const watcher = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) {
        setWidth(entry.contentRect.width);
      }
    });
    watcher.observe(element);
    return () => {
      watcher.disconnect();
    };
  }, []);

  return { box, width };
}
