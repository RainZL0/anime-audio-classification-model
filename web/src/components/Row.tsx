import { useEffect, useRef } from "react";
import type { Clip, Roles } from "../api";
import { bestTarget, chanceOf, lowTip, whoOf, type LabelText } from "../clips";
import { pct, stamp } from "../format";
import { tr } from "../language";
import { needsText } from "../purpose";
import { Avatar } from "./Avatar";
import { Closest, Pill } from "./Pills";
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
      className={`row ${selected ? "sel" : ""} ${flash ? "done-flash" : ""}`}
      onClick={onSelect}
    >
      <Avatar
        role={who && !stranger ? roles[who.name] : undefined}
        name={stranger ? null : who?.name}
        blank={isOther}
      />
      <div>
        <div className="who">
          <span
            className="n"
            style={who && !who.human ? { color: "var(--text-2)", fontWeight: 500 } : undefined}
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
            <span className="pill unusable" title={lowTip()}>
              {tr("质量低", "Low quality")}
            </span>
          )}
          {needsText() && clip.role && clip.spoken_problem && !clip.unusable && (
            <span className="pill no-text" title={clip.spoken_problem}>
              {tr("导不出文字", "No text to export")}
            </span>
          )}
          {clip.maybe && (
            <span
              className="pill maybe"
              title={tr(
                "机器没归给这个角色，但听起来有可能是",
                "The machine didn't give it to this character, but it might be",
              )}
            >
              {tr("可能漏掉", "Maybe missed")} {pct(chanceOf(clip, maybeOf))}
            </span>
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
        <div className={`say ${clip.text ? "" : "empty"}`}>
          {clip.text || tr("（没有字幕文字）", "(no subtitle text)")}
        </div>
        {/* The text written on export, in the language spoken, when it differs from the subtitles. */}
        {clip.spoken && clip.spoken !== clip.text && <div className="spoken">{clip.spoken}</div>}
      </div>
      <div className="t">
        {stamp(clip.start)}
        <br />
        {clip.duration.toFixed(2)}s
      </div>
    </div>
  );
}
