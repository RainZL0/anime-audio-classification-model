import { cn } from "cn";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { Clip } from "../api";
import type { Roles } from "../api";
import { statusText } from "../clips";
import { pct } from "../format";
import { tr } from "../language";
import { Avatar } from "./Avatar";
import { Tip } from "./Tip";

/* The looks of a pill, a small rounded label inside a line of text (see docs/UI_DESIGN.md#color). Green is
   confirmed, orange waits to be checked, red is low quality; a dashed outline is a hint that may be wrong. */
const LOOKS = {
  confirmed: "bg-success/10 text-success",
  auto: "bg-muted text-muted-foreground",
  review: "bg-warning/15 text-warning",
  novoice: "bg-muted text-muted-foreground",
  unlabeled: "bg-muted text-muted-foreground",
  done: "bg-muted text-muted-foreground",
  skipped: "border-border text-muted-foreground",
  stranger: "border-dashed border-muted-foreground/60 text-muted-foreground",
  unusable: "border-destructive text-destructive",
  noText: "border-warning text-warning",
  maybe: "border-dashed border-warning text-warning",
  closest: "border-border bg-muted/60 pl-0.5 text-muted-foreground",
};
export type PillLook = keyof typeof LOOKS;

export function Tag({
  look,
  tip,
  className,
  children,
}: {
  look: PillLook;
  tip?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Tip text={tip}>
      <Badge
        variant="outline"
        className={cn("border-transparent tabular-nums", LOOKS[look], className)}
      >
        {children}
      </Badge>
    </Tip>
  );
}

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
    <Tag
      look="closest"
      tip={title || tr("机器觉得最像的角色", "The character the machine finds closest")}
    >
      <Avatar role={roles[name]} name={name} size="xs" title={name} />
      {tr("最像", "Closest:")} {name}
      {p != null ? ` ${pct(p)}` : ""}
    </Tag>
  );
}

export function Pill({ clip }: { clip: Clip }) {
  if (clip.status === "review" && clip.familiar === false) {
    return (
      <Tag
        look="stranger"
        tip={tr(
          "跟已知角色确认过的台词都不太像",
          "Not much like any confirmed line of a known character",
        )}
      >
        {tr("可能是没见过的人", "Maybe someone new")}
      </Tag>
    );
  }
  if (clip.status === "auto" || clip.status === "review") {
    return (
      <Tag look={clip.status}>
        {clip.status === "review" ? tr("待确认 ", "Check ") : ""}
        {pct(clip.guess[0].p)}
      </Tag>
    );
  }
  return <Tag look={clip.status}>{statusText(clip.status)}</Tag>;
}
