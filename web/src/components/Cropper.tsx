import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { Role } from "../api";
import { tr } from "../language";
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
  const canvas = useRef<HTMLCanvasElement>(null);
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

  /* Once, when the dialog opens: the video and its size do not change while it is open. */
  useEffect(() => {
    if (naming) nameBox.current?.focus();
    if (!source) return;
    source.pause();
    const draw = () => {
      canvas.current?.getContext("2d")?.drawImage(source, 0, 0, W, H);
      setFrame((n) => n + 1);
    };
    draw();
    source.addEventListener("seeked", draw);
    return () => source.removeEventListener("seeked", draw);
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- only once, see above
  }, []);

  useEffect(() => {
    if (!canvas.current || !preview.current) return;
    const ctx = preview.current.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, 96, 96);
    ctx.drawImage(canvas.current, box.x, box.y, box.s, box.s, 0, 0, 96, 96);
  }, [box, frame]);

  const clamp = (b: Box): Box => {
    const s = Math.max(24, Math.min(b.s, W, H));
    return { s, x: Math.min(Math.max(b.x, 0), W - s), y: Math.min(Math.max(b.y, 0), H - s) };
  };
  const at = (e: { clientX: number; clientY: number }) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };
  /* Drag inside the box to move it, drag the bottom-right corner to resize, press outside to draw a new one. */
  const down = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = at(e);
    const inside = p.x >= box.x && p.x <= box.x + box.s && p.y >= box.y && p.y <= box.y + box.s;
    if ((e.target as HTMLElement).classList.contains("handle"))
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
    if (source && withAvatar && canvas.current) {
      const out = document.createElement("canvas");
      out.width = out.height = AVATAR_SIDE;
      out
        .getContext("2d")
        ?.drawImage(canvas.current, box.x, box.y, box.s, box.s, 0, 0, AVATAR_SIDE, AVATAR_SIDE);
      image = out.toDataURL("image/jpeg", 0.9);
    }
    onSave(image, newName);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      /* While an input method is still putting a word together, Enter and Escape belong to it. */
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Enter") {
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
    <div className="overlay" onClick={naming ? undefined : onClose}>
      <div className="cropper" onClick={(e) => e.stopPropagation()}>
        <h2>
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
        </h2>
        {naming && (
          <div className="crop-name">
            <input
              ref={nameBox}
              value={typed}
              placeholder={tr(
                `名字，可以不填，先叫「${name}」`,
                `Name, optional. For now it is "${name}"`,
              )}
              onChange={(e) => {
                setTyped(e.target.value);
                setProblem("");
              }}
            />
            {problem && <p className="note bad">{problem}</p>}
          </div>
        )}
        {source && (
          <>
            {naming && (
              <p className="note">
                {tr("再从画面里截一张头像：", "And crop an avatar from the picture:")}
              </p>
            )}
            <div
              ref={area}
              className="crop-area"
              onPointerDown={down}
              onPointerMove={moveTo}
              onPointerUp={up}
            >
              <canvas ref={canvas} width={W} height={H}></canvas>
              <div
                className="crop-box"
                style={{
                  left: left(box.x, W),
                  top: left(box.y, H),
                  width: left(box.s, W),
                  height: left(box.s, H),
                }}
              >
                <div className="handle"></div>
              </div>
            </div>
            <div className="crop-bar">
              <label className="note">{tr("换一帧", "Pick a frame")}</label>
              <input
                type="range"
                min="0"
                max={source.duration || 0}
                step="0.04"
                value={time}
                onChange={(e) => {
                  const t = Number(e.target.value);
                  setTime(t);
                  source.currentTime = t;
                }}
              />
              <canvas ref={preview} className="crop-preview" width="96" height="96"></canvas>
            </div>
            <p className="note">
              {tr(
                "拖动方框挪位置，拖右下角或滚轮缩放，在框外按下可以重新画。",
                "Drag the box to move it, drag its bottom-right corner or use the wheel to resize, press outside it to draw a new one.",
              )}
            </p>
          </>
        )}
        <div className="crop-actions">
          <button className="ghost" onClick={onClose}>
            {naming ? tr("取消", "Cancel") : tr("放弃", "Cancel")} <kbd>Esc</kbd>
          </button>
          {naming && source && (
            <button onClick={() => save(false)}>{tr("不要头像", "No avatar")}</button>
          )}
          <button className="primary" onClick={() => save()}>
            {naming ? tr("保存", "Save") : tr("用这张", "Use this")} <kbd>Enter</kbd>
          </button>
        </div>
      </div>
    </div>
  );
}
