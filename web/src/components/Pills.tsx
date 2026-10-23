import type { Clip, Roles } from "../api";
import { statusText } from "../clips";
import { pct } from "../format";
import { tr } from "../language";
import { Avatar } from "./Avatar";

/* The machine's guess of who someone is, shown the same way everywhere: a small avatar, "Closest" and the name,
   and the chance when there is one. */
export function Closest({
  roles,
  name,
  p,
  title,
}: {
  roles: Roles;
  name: string;
  p?: number;
  title?: string;
}) {
  return (
    <span
      className="pill closest"
      title={title || tr("机器觉得最像的角色", "The character the machine finds closest")}
    >
      <Avatar role={roles[name]} name={name} size="xs" />
      {tr("最像", "Closest:")} {name}
      {p != null ? ` ${pct(p)}` : ""}
    </span>
  );
}

export function Pill({ clip }: { clip: Clip }) {
  if (clip.status === "review" && clip.familiar === false) {
    return (
      <span
        className="pill stranger"
        title={tr(
          "跟已知角色确认过的台词都不太像",
          "Not much like any confirmed line of a known character",
        )}
      >
        {tr("可能是没见过的人", "Maybe someone new")}
      </span>
    );
  }
  if (clip.status === "auto" || clip.status === "review") {
    return (
      <span className={`pill ${clip.status}`}>
        {clip.status === "review" ? tr("待确认 ", "Check ") : ""}
        {pct(clip.guess[0].p)}
      </span>
    );
  }
  return <span className={`pill ${clip.status}`}>{statusText(clip.status)}</span>;
}
