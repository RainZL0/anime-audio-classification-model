import { cn } from "cn";
import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Choice } from "../components/Choice";
import type { Clip, Roles } from "../api";
import { NEEDS_WORK, skippedTip, type LabelText } from "../clips";
import { EpisodeProgress, type Progress } from "../components/EpisodeProgress";
import { Empty } from "../components/Notes";
import { Row } from "../components/Row";
import { Tip } from "../components/Tip";
import { stamp } from "../format";
import { lines, tr } from "../language";

interface SceneViewProps {
  clips: Clip[];
  order: string[];
  focus: string | null;
  setFocus: (id: string) => void;
  roles: Roles;
  labelText: LabelText;
  onlyWork: boolean;
  setOnlyWork: (on: boolean) => void;
  showShort: boolean;
  setShowShort: (on: boolean) => void;
  flashes: Set<string>;
  episode: string | null;
  progress: Progress;
}

/* ───────────── Scenes view ───────────── */

export function SceneView({
  clips,
  order,
  focus,
  setFocus,
  roles,
  labelText,
  onlyWork,
  setOnlyWork,
  showShort,
  setShowShort,
  flashes,
  episode,
  progress,
}: SceneViewProps) {
  const shown = new Set(order);
  const scenes: { scene: number; clips: Clip[] }[] = [];
  for (const clip of clips) {
    if (!shown.has(clip.id)) continue;
    const last = scenes[scenes.length - 1];
    if (!last || last.scene !== clip.scene) scenes.push({ scene: clip.scene, clips: [clip] });
    else last.clips.push(clip);
  }
  const left = clips.filter((c) => NEEDS_WORK.has(c.status)).length;
  const skipped = clips.filter((c) => c.status === "skipped").length;
  /* The summary stays at the top while scrolling, so each scene header sticks just below it, and a selected
     line scrolls into view below both. Its height changes when it wraps, so it is measured. */
  const head = useRef<HTMLDivElement>(null);
  const [headHeight, setHeadHeight] = useState(0);
  useLayoutEffect(() => {
    const box = head.current;
    if (!box) return;
    const watch = new ResizeObserver(() => setHeadHeight(box.offsetHeight));
    watch.observe(box);
    return () => watch.disconnect();
  }, []);
  return (
    <div
      style={{ "--head": `${headHeight}px` } as CSSProperties}
      className="[&_section>*]:scroll-mt-(--head)"
    >
      {/* -top-2 cancels the top padding of the list, so lines don't show through above it. */}
      <div
        ref={head}
        className="sticky -top-2 z-[3] flex flex-wrap items-center gap-2.5 border-b bg-background px-1 pt-3 pb-2"
      >
        <h2 className="text-base font-semibold">{episode}</h2>
        <EpisodeProgress progress={progress} />
        <span className="text-xs text-muted-foreground">
          {tr(
            `${clips.length} 句 · 还有 ${left} 句要你看`,
            `${lines(clips.length)} · ${left} left for you`,
          )}
        </span>
        {skipped > 0 && (
          <>
            <Tip text={skippedTip()}>
              <span className="text-xs text-muted-foreground">
                · {tr(`跳过 ${skipped} 句`, `${lines(skipped)} skipped`)}
              </span>
            </Tip>
            {/* Grayed out under "Only to do", not hidden: skipped lines are not work to do. The span holds the
                hint, since a disabled button gets no mouse events. */}
            <Tip
              text={
                onlyWork
                  ? tr(
                      "只在「整集」里能显示：跳过的台词不算要处理的",
                      "Only under Whole episode: skipped lines are not work to do",
                    )
                  : tr(
                      "在「整集」里显示跳过的台词，想标也可以标",
                      "Show the skipped lines under Whole episode; you can still label them",
                    )
              }
            >
              <span>
                <Button
                  variant="outline"
                  size="xs"
                  disabled={onlyWork}
                  aria-pressed={showShort && !onlyWork}
                  className={cn(
                    showShort && !onlyWork && "border-primary/40 bg-accent hover:bg-accent",
                  )}
                  onClick={() => setShowShort(!showShort)}
                >
                  {showShort && !onlyWork
                    ? tr("隐藏跳过的", "Hide skipped")
                    : tr("显示跳过的", "Show skipped")}
                </Button>
              </span>
            </Tip>
          </>
        )}
        <span className="flex-1"></span>
        <Choice
          value={onlyWork ? "work" : "all"}
          options={[
            ["all", tr("整集", "Whole episode")],
            [
              "work",
              <>
                {tr("只看要处理的", "Only to do")} <Kbd>F</Kbd>
              </>,
            ],
          ]}
          onPick={(v) => setOnlyWork(v === "work")}
        />
      </div>
      {scenes.length === 0 && (
        <Empty title={tr("这一集都处理完了", "This episode is done")}>
          <p>
            {tr(
              "切到「整集」可以回头翻看，或者去「角色」视图按人核对机器的判断。",
              "Switch to Whole episode to look back, or check the machine's calls per character in the Characters view.",
            )}
          </p>
        </Empty>
      )}
      {scenes.map((s) => (
        <section key={`${s.scene}-${s.clips[0].id}`}>
          {/* Sticks right under the summary, which sits 0.5rem above the top of the list. */}
          <div className="sticky top-[calc(var(--head)-0.5rem)] z-[2] flex items-center gap-2 bg-background px-1 pt-3.5 pb-1.5 text-xs text-muted-foreground">
            <b className="font-semibold text-foreground/80">
              {tr(`第 ${s.scene + 1} 场`, `Scene ${s.scene + 1}`)}
            </b>
            <span>{stamp(s.clips[0].start)}</span>
            <span>· {lines(s.clips.length)}</span>
          </div>
          {s.clips.map((clip) => (
            <Row
              key={clip.id}
              clip={clip}
              roles={roles}
              labelText={labelText}
              selected={clip.id === focus}
              flash={flashes.has(clip.id)}
              onSelect={() => setFocus(clip.id)}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
