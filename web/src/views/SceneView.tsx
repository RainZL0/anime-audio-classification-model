import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Choice } from "../components/Choice";
import type { Clip, Roles } from "../api";
import { NEEDS_WORK, type LabelText } from "../clips";
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
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2.5 px-1 pt-3 pb-1">
        <h2 className="text-base font-semibold">{episode}</h2>
        <span className="text-xs text-muted-foreground">
          {tr(
            `${clips.length} 句 · 还有 ${left} 句要你看`,
            `${lines(clips.length)} · ${left} left for you`,
          )}
        </span>
        {skipped > 0 && (
          <>
            <Tip
              text={tr(
                "短于 1 秒、前后 0.5 秒内没有别的台词，训练用不上，默认不显示",
                "Shorter than 1 second with no other line within 0.5 seconds: no use for training, hidden by default",
              )}
            >
              <span className="text-xs text-muted-foreground">
                ·{" "}
                {tr(
                  `跳过 ${skipped} 句短句`,
                  `${skipped} short ${skipped === 1 ? "line" : "lines"} skipped`,
                )}
              </span>
            </Tip>
            {!onlyWork && (
              <Tip
                text={tr(
                  "在「整集」里显示跳过的短句，想标也可以标",
                  "Show the skipped short lines under Whole episode; you can still label them",
                )}
              >
                <Button
                  variant="outline"
                  size="xs"
                  aria-pressed={showShort}
                  className={cn(showShort && "border-primary/40 bg-accent hover:bg-accent")}
                  onClick={() => setShowShort(!showShort)}
                >
                  {showShort
                    ? tr("隐藏短句", "Hide short lines")
                    : tr("显示短句", "Show short lines")}
                </Button>
              </Tip>
            )}
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
          {/* -top-2 cancels the top padding of the list, so lines don't show through above a stuck header. */}
          <div className="sticky -top-2 z-[2] flex items-center gap-2 bg-background px-1 pt-3.5 pb-1.5 text-xs text-muted-foreground">
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
