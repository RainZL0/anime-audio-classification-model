import { cn } from "cn";
import type { CSSProperties } from "react";
import type { Role } from "../api";
import { tr } from "../language";
import { Tip } from "./Tip";

/* The picture for a character without an avatar: background color × white shape × pattern.
   The number is given out by the server and kept in the character list, so a character always gets the
   same picture. */
const PALETTE = [
  "#7F77DD",
  "#1D9E75",
  "#D85A30",
  "#D4537E",
  "#378ADD",
  "#639922",
  "#BA7517",
  "#E24B4A",
  "#5F5E5A",
  "#534AB7",
  "#0F6E56",
  "#993C1D",
  "#993556",
  "#185FA5",
  "#3B6D11",
  "#854F0B",
];

/* Corners of a polygon centered at (20, 20), its radius taking the values in radii in turn. */
const ring = (corners: number, radii: number[], turn = -Math.PI / 2) =>
  Array.from({ length: corners }, (_, i) => {
    const r = radii[i % radii.length];
    const a = turn + (2 * Math.PI * i) / corners;
    return `${(20 + r * Math.cos(a)).toFixed(1)},${(20 + r * Math.sin(a)).toFixed(1)}`;
  }).join(" ");

const SHAPES = [
  <circle key="0" cx="20" cy="20" r="9" />,
  <polygon key="1" points="20,8 32,20 20,32 8,20" />,
  <polygon key="2" points="20,9 32,30 8,30" />,
  <rect key="3" x="11" y="11" width="18" height="18" rx="2.5" />,
  <polygon key="4" points={ring(10, [12, 5])} />,
  <polygon key="5" points={ring(6, [11], 0)} />,
  <path key="6" d="M16 9h8v7h7v8h-7v7h-8v-7H9v-8h7z" />,
  <circle key="7" cx="20" cy="20" r="8" fill="none" stroke="#fff" strokeWidth="4.5" />,
];

function hashed(text: string) {
  let h = 0;
  for (const ch of text) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return h;
}

/* Number p takes color p % 16. The shape shifts by 3 after each round of 16 colors (3 and 8 share no factor),
   so the first 128 numbers all get a different color × shape; only after that does the pattern tell them apart. */
function Pattern({ role, name }: { role?: Role; name: string }) {
  const p = role?.pattern ?? hashed(name);
  const color = role?.color || PALETTE[p % PALETTE.length];
  const round = Math.floor(p / PALETTE.length);
  const shape = ((p % SHAPES.length) + 3 * round) % SHAPES.length;
  const variant = Math.floor(p / (PALETTE.length * SHAPES.length)) % 3;
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" className="block size-full">
      <rect width="40" height="40" fill={color} />
      {variant === 1 && <path d="M0 40L40 0V40z" fill="rgba(0,0,0,.22)" />}
      {variant === 2 && (
        <circle cx="20" cy="20" r="17" fill="none" stroke="rgba(255,255,255,.55)" strokeWidth="2" />
      )}
      <g fill="#fff">{SHAPES[shape]}</g>
    </svg>
  );
}

const SIZES = {
  xs: "size-4 text-[9px]",
  sm: "size-[26px] text-[11px]",
  base: "size-[34px] text-[13px]",
  md: "size-10 text-[15px]",
  lg: "size-14 text-[19px]",
  xl: "size-[88px] text-[26px]",
};

interface AvatarProps {
  role?: Role;
  name?: string | null;
  size?: keyof typeof SIZES;
  /* A gray circle with a dot, for "other". */
  blank?: boolean;
  /* A gray circle with a plus, for "New character". */
  plus?: boolean;
  onClick?: (() => void) | null;
  title?: string;
}

export function Avatar({ role, name, size = "base", blank, plus, onClick, title }: AvatarProps) {
  const base = cn(
    "grid flex-none place-items-center overflow-hidden rounded-full bg-cover bg-center font-semibold text-white ring-1 ring-border select-none",
    SIZES[size],
  );
  if (blank || plus || !name)
    return (
      <div className={cn(base, "bg-muted text-muted-foreground")}>
        {blank ? "·" : plus ? "+" : "?"}
      </div>
    );
  /* A clickable avatar says "Crop" on hover, when it is big enough to hold the word. */
  const edit =
    onClick &&
    cn(
      "relative cursor-pointer hover:ring-2 hover:ring-primary",
      size !== "xs" &&
        size !== "sm" &&
        "hover:after:absolute hover:after:inset-x-0 hover:after:bottom-0 hover:after:bg-black/55 hover:after:text-center hover:after:text-[10px] hover:after:leading-relaxed hover:after:font-medium hover:after:content-[var(--crop)]",
    );
  const style = {
    ...(onClick && { "--crop": `"${tr("截取", "Crop")}"` }),
    ...(role?.avatar && { backgroundImage: `url(/media/avatar/${role.avatar})` }),
  } as CSSProperties;
  return (
    <Tip text={title}>
      <div
        className={cn(base, edit)}
        onClick={onClick ?? undefined}
        role={onClick ? "button" : undefined}
        style={style}
      >
        {!role?.avatar && <Pattern role={role} name={name} />}
      </div>
    </Tip>
  );
}
