import { useEffect, useRef, type RefObject } from "react";

export function ResizeHandle({
  host,
  property,
  label,
  min,
  max,
  initial,
  direction = 1,
  onChange,
}: {
  host: RefObject<HTMLElement | null>;
  property: string;
  label: string;
  min: number;
  max: number;
  initial: number;
  direction?: number;
  onChange: (width: number) => void;
}) {
  const cleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanup.current?.(), []);
  function apply(width: number) {
    const value = Math.round(Math.max(min, Math.min(max, width)));
    host.current?.style.setProperty(property, value + "px");
    return value;
  }
  return (
    <div
      className="panel-resizer"
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={initial}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          onChange(
            apply(initial + (e.key === "ArrowRight" ? 20 : -20) * direction),
          );
        }
      }}
      onPointerDown={(e) => {
        e.preventDefault();
        cleanup.current?.();
        const start = e.clientX;
        let value = initial;
        const move = (event: PointerEvent) => {
          value = apply(initial + (event.clientX - start) * direction);
        };
        const stop = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", stop);
          window.removeEventListener("pointercancel", stop);
          onChange(value);
        };
        cleanup.current = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", stop);
          window.removeEventListener("pointercancel", stop);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop, { once: true });
        window.addEventListener("pointercancel", stop, { once: true });
      }}
    />
  );
}
