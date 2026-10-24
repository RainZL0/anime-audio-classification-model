import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Slider } from "@/components/ui/slider";
import type { Role } from "../api";
import { tr } from "../language";
import { Note } from "./Notes";
import { RoleName } from "./RoleName";

/* ───────────── Cropping an avatar from the picture ───────────── */

const AVATAR_SIDE = 256;

interface Box {
  x: number;
  y: number;
  s: number;
}

type Drag = { mode: "size"; ox: number; oy: number } | { mode: "move"; dx: number; dy: number };

interface CropperProps {
  source: HTMLVideoElement | null;
  name: string;
  role?: Role;
  naming?: boolean;
  /* Why a typed name can't be used, or "" when it can. */
  taken: (typed: string) => string;
  onSave: (image: string | null, typed: string) => void;
  onClose: () => void;
}

export function Cropper({ source, name, role, naming, taken, onSave, onClose }: CropperProps) {
  /* The dialog puts its content on the page one step after it opens, so the picture's canvas is kept as state:
     the frame is drawn once the canvas is there. */
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  const preview = useRef<HTMLCanvasElement>(null);
  const area = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const nameBox = useRef<HTMLInputElement>(null);
  /* For a new character there is also a name box. Without a picture (no video, or the frame shows someone else),
     there is only the name box. */
  const W = source?.videoWidth || 0;
  const H = source?.videoHeight || 0;
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState("");
  /* The box is square, in the video's own pixels. By default it is the middle of the picture, 60% of its height. */
  const [box, setBox] = useState<Box>(() => {
    const s = Math.round(H * 0.6);
    return { x: Math.round((W - s) / 2), y: Math.round((H - s) / 2), s };
  });
  const [time, setTime] = useState(source?.currentTime || 0);
  const [frame, setFrame] = useState(0);

  /* Once, when the dialog opens: the video and its size do not change while it is open. The name box gets the
     focus through the dialog's initialFocus below. */
  useEffect(() => {
    if (!source || !canvas) return;
    source.pause();
    const draw = () => {
      canvas.getContext("2d")?.drawImage(source, 0, 0, W, H);
      setFrame((n) => n + 1);
    };
    draw();
    source.addEventListener("seeked", draw);
    return () => source.removeEventListener("seeked", draw);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only once, see above
  }, [canvas]);

  useEffect(() => {
    if (!canvas || !preview.current) return;
    const ctx = preview.current.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, 96, 96);
    ctx.drawImage(canvas, box.x, box.y, box.s, box.s, 0, 0, 96, 96);
  }, [box, frame, canvas]);

  const clamp = (b: Box): Box => {
    const s = Math.max(24, Math.min(b.s, W, H));
    return { s, x: Math.min(Math.max(b.x, 0), W - s), y: Math.min(Math.max(b.y, 0), H - s) };
  };
  const at = (e: { clientX: number; clientY: number }) => {
    const r = canvas!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };
  /* Drag inside the box to move it, drag the bottom-right corner to resize, press outside to draw a new one. */
  const down = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = at(e);
    const inside = p.x >= box.x && p.x <= box.x + box.s && p.y >= box.y && p.y <= box.y + box.s;
    if ((e.target as HTMLElement).hasAttribute("data-handle"))
      drag.current = { mode: "size", ox: box.x, oy: box.y };
    else if (inside) drag.current = { mode: "move", dx: p.x - box.x, dy: p.y - box.y };
    else {
      drag.current = { mode: "size", ox: p.x, oy: p.y };
      setBox(clamp({ x: p.x, y: p.y, s: 24 }));
    }
  };
  const moveTo = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = at(e);
    if (d.mode === "move") setBox(clamp({ ...box, x: p.x - d.dx, y: p.y - d.dy }));
    else {
      const s = Math.max(p.x - d.ox, p.y - d.oy, 24);
      setBox(clamp({ x: d.ox, y: d.oy, s: Math.min(s, W - d.ox, H - d.oy) }));
    }
  };
  const up = () => {
    drag.current = null;
  };
  /* React listens to the wheel without being able to stop the page from scrolling, so this one is added by hand. */
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const grow = e.deltaY < 0 ? 1.06 : 1 / 1.06;
      const s = box.s * grow;
      setBox(clamp({ x: box.x + (box.s - s) / 2, y: box.y + (box.s - s) / 2, s }));
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });
  /* withAvatar false: keep only the name. */
  const save = (withAvatar = true) => {
    /* Read the box itself: a quick Enter can come before the page has drawn the last letter typed. */
    const newName = naming ? (nameBox.current?.value ?? typed).trim() : "";
    const wrong = newName ? taken(newName) : "";
    if (wrong) {
      setProblem(wrong);
      nameBox.current?.focus();
      return;
    }
    let image: string | null = null;
    if (source && withAvatar && canvas) {
      const out = document.createElement("canvas");
      out.width = out.height = AVATAR_SIDE;
      out
        .getContext("2d")
        ?.drawImage(canvas, box.x, box.y, box.s, box.s, 0, 0, AVATAR_SIDE, AVATAR_SIDE);
      image = out.toDataURL("image/jpeg", 0.9);
    }
    onSave(image, newName);
  };
  /* Escape is handled by the dialog itself, which also leaves it to an input method still putting a word
     together; it ends in onOpenChange below. */
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      /* While an input method is still putting a word together, Enter and Escape belong to it. */
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Enter") {
        e.preventDefault();
        save();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const left = (v: number, total: number) => `${(v / total) * 100}%`;
  /* For a new character, a click beside the dialog does nothing: closing it there would cancel the new character. */
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      disablePointerDismissal={naming}
    >
      <DialogContent
        showCloseButton={false}
        initialFocus={naming ? nameBox : undefined}
        className="gap-2.5 p-4 sm:max-w-[min(760px,94vw)]"
      >
        <DialogTitle className="text-base font-semibold">
          {naming
            ? tr("新角色", "New character")
            : tr(
                <>
                  给 <RoleName role={role} name={name} /> 截一张头像
                </>,
                <>
                  Crop an avatar for <RoleName role={role} name={name} />
                </>,
              )}
        </DialogTitle>
        {naming && (
          <div>
            <Input
              ref={nameBox}
              value={typed}
              aria-invalid={!!problem || undefined}
              className="h-9 text-[15px] md:text-[15px]"
              placeholder={tr(
                `名字，可以不填，先叫「${name}」`,
                `Name, optional. For now it is "${name}"`,
              )}
              onChange={(e) => {
                setTyped(e.target.value);
                setProblem("");
              }}
            />
            {problem && <p className="mt-1.5 text-xs text-destructive">{problem}</p>}
          </div>
        )}
        {source && (
          <>
            {naming && (
              <Note>{tr("再从画面里截一张头像：", "And crop an avatar from the picture:")}</Note>
            )}
            {/* Always dark, like the video screen, in both themes. */}
            <div
              ref={area}
              className="relative cursor-crosshair touch-none overflow-hidden rounded-lg bg-neutral-950 leading-none"
              onPointerDown={down}
              onPointerMove={moveTo}
              onPointerUp={up}
            >
              <canvas ref={setCanvas} width={W} height={H} className="block h-auto w-full"></canvas>
              <div
                className="absolute cursor-move rounded-full shadow-[0_0_0_9999px_rgb(0_0_0/0.55)] outline-2 outline-white before:absolute before:inset-0 before:border before:border-dashed before:border-white/60"
                style={{
                  left: left(box.x, W),
                  top: left(box.y, H),
                  width: left(box.s, W),
                  height: left(box.s, H),
                }}
              >
                <div
                  data-handle
                  className="absolute -right-[7px] -bottom-[7px] size-3.5 cursor-nwse-resize rounded-[3px] bg-white shadow-[0_0_0_1px_rgb(0_0_0/0.4)]"
                ></div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <label className="text-xs whitespace-nowrap text-muted-foreground">
                {tr("换一帧", "Pick a frame")}
              </label>
              <Slider
                className="flex-1"
                min={0}
                max={source.duration || 0}
                step={0.04}
                value={[time]}
                onValueChange={(v) => {
                  const t = Array.isArray(v) ? v[0] : v;
                  setTime(t);
                  source.currentTime = t;
                }}
              />
              <canvas
                ref={preview}
                className="size-18 flex-none rounded-full ring-1 ring-input"
                width="96"
                height="96"
              ></canvas>
            </div>
            <Note>
              {tr(
                "拖动方框挪位置，拖右下角或滚轮缩放，在框外按下可以重新画。",
                "Drag the box to move it, drag its bottom-right corner or use the wheel to resize, press outside it to draw a new one.",
              )}
            </Note>
          </>
        )}
        <DialogFooter className="mt-1.5">
          <Button variant="ghost" onClick={onClose}>
            {naming ? tr("取消", "Cancel") : tr("放弃", "Cancel")} <Kbd>Esc</Kbd>
          </Button>
          {naming && source && (
            <Button variant="outline" onClick={() => save(false)}>
              {tr("不要头像", "No avatar")}
            </Button>
          )}
          <Button onClick={() => save()}>
            {naming ? tr("保存", "Save") : tr("用这张", "Use this")} <Kbd>Enter</Kbd>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
