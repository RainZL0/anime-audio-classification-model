import { cn } from "cn";
import { useState, type PointerEvent } from "react";
import { tr } from "../language";
import { fitStage, STAGE_WIDTH } from "../stageWidth";
import { Tip } from "./Tip";

/* While dragging, the whole page shows the resize cursor, text is not selected by mistake, and the video does not
   take the pointer. Set on the page itself, since the pointer leaves the strip. */
function dragLook(on: boolean) {
  document.body.style.cursor = on ? "col-resize" : "";
  document.body.style.userSelect = on ? "none" : "";
  for (const video of document.querySelectorAll("video"))
    video.style.pointerEvents = on ? "none" : "";
}

/* ───────────── The line between the stage and the list: drag it to change the width ───────────── */

export function Divider({ width, setWidth }: { width: number; setWidth: (width: number) => void }) {
  const [dragging, setDragging] = useState(false);
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
      setDragging(false);
      dragLook(false);
      localStorage.setItem("stage-width", String(last));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    setDragging(true);
    dragLook(true);
  };
  const reset = () => {
    setWidth(STAGE_WIDTH);
    localStorage.removeItem("stage-width");
  };
  /* A 1px line inside a wider strip that is easier to grab. */
  return (
    <Tip
      text={tr(
        "拖动调整左右宽度，双击恢复默认",
        "Drag to change the widths, double-click to reset",
      )}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        className="group z-1 -mx-[3px] flex w-[7px] cursor-col-resize touch-none justify-center"
        onPointerDown={start}
        onDoubleClick={reset}
      >
        <div
          className={cn(
            "h-full w-px bg-border transition-colors group-hover:w-[3px] group-hover:bg-ring",
            dragging && "w-[3px] bg-ring",
          )}
        />
      </div>
    </Tip>
  );
}
