import { cn } from "cn";
import { useEffect, useRef } from "react";
import type { Clip, Roles } from "../api";
import { bestTarget, chanceOf, lowTip, whoOf, type LabelText } from "../clips";
import { pct, stamp } from "../format";
import { tr } from "../language";
import { needsText } from "../purpose";
import { Avatar } from "./Avatar";
import { Closest, NoText, Pill, Tag } from "./Pills";
import { RoleName } from "./RoleName";

interface RowProps {
  clip: Clip;
  roles: Roles;
  labelText: LabelText;
  selected: boolean;
  onSelect: () => void;
  flash: boolean;
  /* In "Maybe missed": the character it may belong to. */
  maybeOf?: string;
  /* Show the target character the machine finds closest, for lines of "other". */
  showTarget?: boolean;
  /* Show which episode the line is from, in lists that cover all episodes. */
  showEpisode?: boolean;
  /* Scroll the line into view when it becomes selected. Off in lists that only draw the lines near the screen:
     there a line is drawn again each time it scrolls back in, and the list scrolls to it itself. */
  follow?: boolean;
}

/* The look of the selected line, the same in every list. The line needs `border border-transparent` so it
   doesn't move when selected. */
export const SELECTED_ROW = "border-primary/40 bg-accent shadow-sm hover:bg-accent";

/* ───────────── One line ───────────── */

export function Row({
  clip,
  roles,
  labelText,
  selected,
  onSelect,
  flash,
  maybeOf,
  showTarget,
  showEpisode,
  follow = true,
}: RowProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow && selected && ref.current) ref.current.scrollIntoView({ block: "nearest" });
  }, [selected, follow]);
  const who = whoOf(clip);
  const isOther = !!who && !!labelText[who.name];
  const stranger = !clip.label && clip.familiar === false;
  const best = bestTarget(clip);
  return (
    <div
      ref={ref}
      className={cn(
        "relative isolate grid grid-cols-[36px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-[7px] hover:bg-muted/60",
        selected && SELECTED_ROW,
      )}
      onClick={onSelect}
    >
      {/* Just labeled: a green background that fades out. It sits behind the row's content. */}
      {flash && (
        <span className="pointer-events-none absolute inset-0 -z-10 animate-out rounded-[inherit] bg-success/10 duration-900 ease-out fill-mode-forwards fade-out" />
      )}
      <Avatar
        role={who && !stranger ? roles[who.name] : undefined}
        name={stranger ? null : who?.name}
        blank={isOther}
      />
      <div>
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
          <span
            className={cn(
              "font-semibold text-foreground",
              who && !who.human && "font-medium text-muted-foreground",
            )}
          >
            {stranger ? (
              ""
            ) : isOther ? (
              labelText[who.name]
            ) : who ? (
              <RoleName role={roles[who.name]} name={who.name} />
            ) : (
              tr("未知", "Unknown")
            )}
          </span>
          {/* In "Maybe missed" the chance for the current owner is left out: with two people it is just 100% minus
              the chance shown on the maybe pill. */}
          {!(
            clip.maybe &&
            clip.familiar !== false &&
            (clip.status === "auto" || clip.status === "review")
          ) && <Pill clip={clip} />}
          {/* No chance here: it is among the known characters only, so it can be high for someone new. */}
          {stranger && best && <Closest roles={roles} name={best.name} />}
          {clip.unusable && !(clip.label && labelText[clip.label]) && (
            <Tag look="unusable" tip={lowTip()}>
              {tr("质量低", "Low quality")}
            </Tag>
          )}
          {needsText() && clip.role && clip.spoken_problem && !clip.unusable && (
            <NoText problem={clip.spoken_problem} />
          )}
          {clip.maybe && (
            <Tag
              look="maybe"
              tip={tr(
                `机器猜这句是 ${maybeOf} 的概率。它没归给 ${maybeOf}，但有可能是`,
                `The machine's chance that this line is ${maybeOf}. It didn't give it to them, but it might be`,
              )}
            >
              {tr("可能漏掉", "Maybe missed")} {pct(chanceOf(clip, maybeOf))}
            </Tag>
          )}
          {showTarget && best && (
            <Closest
              roles={roles}
              name={best.name}
              p={best.p}
              title={tr(
                "机器觉得这句是这个目标角色的概率",
                "The machine's chance that this line is this target character",
              )}
            />
          )}
        </div>
        <div className={cn("mt-px text-[15px]", !clip.text && "text-muted-foreground italic")}>
          {clip.text || tr("（没有字幕文字）", "(no subtitle text)")}
        </div>
        {/* The secondary subtitle line, such as a translation. */}
        {clip.display && clip.display !== clip.text && (
          <div className="mt-px text-[13px] text-muted-foreground">{clip.display}</div>
        )}
        {/* The text written on export, in the language spoken, when it differs from the main subtitles. Only when
            the text is exported at all (see purpose.ts). */}
        {needsText() && clip.spoken && clip.spoken !== clip.text && (
          <div className="mt-px text-[13px] text-muted-foreground">{clip.spoken}</div>
        )}
      </div>
      <div className="text-right text-[11px] whitespace-nowrap text-muted-foreground tabular-nums">
        {showEpisode && `${clip.episode} `}
        {stamp(clip.start)}
        <br />
        {clip.duration.toFixed(2)}s
      </div>
    </div>
  );
}
