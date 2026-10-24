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
}

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
}: RowProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected && ref.current) ref.current.scrollIntoView({ block: "nearest" });
  }, [selected]);
  const who = whoOf(clip);
  const isOther = !!who && !!labelText[who.name];
  const stranger = !clip.label && clip.familiar === false;
  const best = bestTarget(clip);
  return (
    <div
      ref={ref}
      className={cn(
        "relative isolate grid cursor-pointer grid-cols-[36px_1fr_auto] items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-[7px] hover:bg-muted/60",
        selected && "border-primary/40 bg-accent shadow-sm hover:bg-accent",
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
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
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
          <Pill clip={clip} />
          {stranger && best && <Closest roles={roles} name={best.name} p={best.p} />}
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
                "机器没归给这个角色，但听起来有可能是",
                "The machine didn't give it to this character, but it might be",
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
        {/* The text written on export, in the language spoken, when it differs from the subtitles. */}
        {clip.spoken && clip.spoken !== clip.text && (
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
