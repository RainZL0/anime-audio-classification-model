import type { PointerEvent } from "react";
import { tr } from "../language";
import { fitStage, STAGE_WIDTH } from "../stageWidth";

/* ───────────── The line between the stage and the list: drag it to change the width ───────────── */

export function Divider({ width, setWidth }: { width: number; setWidth: (width: number) => void }) {
  const start = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const from = e.clientX - width;
    let last = width;
    const move = (m: globalThis.PointerEvent) => {
      last = fitStage(m.clientX - from);
      setWidth(last);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      document.body.classList.remove("dragging-divider");
      localStorage.setItem("stage-width", String(last));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    document.body.classList.add("dragging-divider");
  };
  const reset = () => {
    setWidth(STAGE_WIDTH);
    localStorage.removeItem("stage-width");
  };
  return (
    <div
      className="divider"
      role="separator"
      aria-orientation="vertical"
      title={tr(
        "拖动调整左右宽度，双击恢复默认",
        "Drag to change the widths, double-click to reset",
      )}
      onPointerDown={start}
      onDoubleClick={reset}
    />
  );
}
