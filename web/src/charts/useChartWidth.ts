/**
 * Measuring how wide a chart's box actually is, in real pixels.
 *
 * This exists to avoid one specific trap. An SVG with a `viewBox` and a width of 100% scales
 * everything inside it to fit — including the type. The same 12px axis label then renders at
 * about 7px on a narrow window and about 22px on a wide monitor, and the chart becomes the only
 * text on the page that is not the page's own size.
 *
 * The fix is dull: never scale the drawing. Measure the box, draw at exactly that size, and let
 * every label render at the size the stylesheet asked for.
 *
 * The width is nothing until the box has been measured once, and the caller draws no marks until
 * then. The card keeps its height throughout, so nothing on the page moves when the marks arrive.
 */
import { useEffect, useRef, useState } from "react";

/**
 * Watch a box and report how wide it is.
 *
 * @returns A reference to attach to the box, and its width in pixels — zero until it has been
 *   measured, which is the caller's signal that there is nothing to draw yet.
 */
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
    // Set once up front: a box that never changes size would otherwise wait for a resize that
    // never comes, and the chart would stay empty on a window nobody touched.
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
