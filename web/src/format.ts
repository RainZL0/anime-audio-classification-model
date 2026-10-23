import { tr } from "./language";

/* Round to tenths of a second first, then split into minutes and seconds, so 59.96 s is not written ":60.0"
   with the minute not carried. */
export const stamp = (s: number) => {
  const tenths = Math.round(s * 10);
  return `${String(Math.floor(tenths / 600)).padStart(2, "0")}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
};

export const pct = (p: number) => `${Math.round(p * 100)}%`;

/* A total length: seconds under a minute, minutes and seconds under an hour, else hours and minutes. */
export const howLong = (seconds: number) => {
  const s = Math.round(seconds);
  if (s < 60) return tr(`${s} 秒`, `${s} s`);
  const m = Math.floor(s / 60);
  return m < 60
    ? tr(`${m} 分 ${s % 60} 秒`, `${m} min ${s % 60} s`)
    : tr(`${Math.floor(m / 60)} 小时 ${m % 60} 分`, `${Math.floor(m / 60)} h ${m % 60} min`);
};

/* Minutes and seconds, such as 3:07. */
export const minutes = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s) % 60).padStart(2, "0")}`;
