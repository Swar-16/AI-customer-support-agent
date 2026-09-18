// apps/web/src/features/chat/use-conversation-capacity.ts
import { useEffect, useRef, useState } from 'react';

export function conversationCapacity(
  availableHeight: number,
  rowHeight: number,
  gap: number,
): number {
  if (
    !Number.isFinite(availableHeight) ||
    !Number.isFinite(rowHeight) ||
    !Number.isFinite(gap) ||
    availableHeight <= 0 ||
    rowHeight <= 0 ||
    gap < 0
  ) {
    return 1;
  }

  // Include the final row without requiring a gap after it.
  return Math.min(200, Math.max(1, Math.floor((availableHeight + gap) / (rowHeight + gap))));
}

export function useConversationCapacity() {
  const listAreaRef = useRef<HTMLDivElement>(null);

  // One row is a safe initial capacity before browser measurement.
  const [limit, setLimit] = useState(1);

  useEffect(() => {
    const element = listAreaRef.current;
    if (!element) return;

    let frame: number | null = null;

    function measure() {
      frame = null;
      if (!element) return;

      const styles = window.getComputedStyle(element);
      const rowHeight = Number.parseFloat(styles.getPropertyValue('--conversation-row-height'));
      const gap = Number.parseFloat(styles.getPropertyValue('--conversation-row-gap'));

      const next = conversationCapacity(
        element.clientHeight,
        Number.isFinite(rowHeight) ? rowHeight : 48,
        Number.isFinite(gap) ? gap : 8,
      );

      setLimit((current) => (current === next ? current : next));
    }

    function scheduleMeasurement() {
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measure);
    }

    const observer =
      typeof ResizeObserver === 'function' ? new ResizeObserver(scheduleMeasurement) : null;

    observer?.observe(element);
    window.addEventListener('resize', scheduleMeasurement);
    scheduleMeasurement();

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', scheduleMeasurement);

      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, []);

  return { listAreaRef, limit };
}
