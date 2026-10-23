import type { Role } from "../api";

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
    <svg viewBox="0 0 40 40" aria-hidden="true">
      <rect width="40" height="40" fill={color} />
      {variant === 1 && <path d="M0 40L40 0V40z" fill="rgba(0,0,0,.22)" />}
      {variant === 2 && (
        <circle cx="20" cy="20" r="17" fill="none" stroke="rgba(255,255,255,.55)" strokeWidth="2" />
      )}
      <g fill="#fff">{SHAPES[shape]}</g>
    </svg>
  );
}

interface AvatarProps {
  role?: Role;
  name?: string | null;
  size?: string;
  /* An empty circle, for "other". */
  blank?: boolean;
  onClick?: (() => void) | null;
  title?: string;
}

export function Avatar({ role, name, size = "", blank, onClick, title }: AvatarProps) {
  if (blank) return <div className={`av ${size} unknown`}>·</div>;
  if (!name) return <div className={`av ${size} unknown`}>?</div>;
  const click = onClick ? { onClick, role: "button" } : {};
  if (role?.avatar) {
    return (
      <div
        className={`av ${size} ${onClick ? "edit" : ""}`}
        title={title || name}
        {...click}
        style={{ backgroundImage: `url(/media/avatar/${role.avatar})` }}
      ></div>
    );
  }
  return (
    <div className={`av ${size} ${onClick ? "edit" : ""}`} title={title || name} {...click}>
      <Pattern role={role} name={name} />
    </div>
  );
}
