import { cn } from "cn";
import { useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import type { Clip, Group, Roles } from "../api";
import { lowTip, OTHER, type LabelText } from "../clips";
import { Avatar } from "../components/Avatar";
import { Chip, LowButton } from "../components/Chip";
import { EpisodeProgress, type Progress } from "../components/EpisodeProgress";
import { Empty, Welcome } from "../components/Notes";
import { Closest, Tag } from "../components/Pills";
import { SELECTED_ROW } from "../components/Row";
import { RoleName } from "../components/RoleName";
import { withKeys } from "../components/Keys";
import { Tip } from "../components/Tip";
import { stamp } from "../format";
import { lines, many, tr } from "../language";

/* A group as the page keeps it: the server's group, with its place in the list as a key. */
export interface KeyedGroup extends Group {
  key: number;
}

/* The ticked lines in each group, by the group's key. */
export type Picked = Record<number, Set<string> | undefined>;

interface GroupsViewProps {
  groups: KeyedGroup[];
  loading: boolean;
  roles: Roles;
  dock: string[];
  labelText: LabelText;
  onName: (ids: string[], name: string, low?: boolean) => void;
  onNew: (ids: string[]) => void;
  focus: string | null;
  setFocus: (id: string) => void;
  firstRun: boolean;
  picked: Picked;
  setPicked: (next: Picked | ((p: Picked) => Picked)) => void;
  episode: string | null;
  progress: Progress;
  /* Lines still to do in this episode, as counted on the Scenes tab. */
  work: number;
}

const GUESSED_MOST = () =>
  tr("机器在这组里最常猜的角色", "The character the machine guesses most often in this group");

/* ───────────── Groups view: name a group of similar voices ───────────── */

/* `picked`: the ticked lines in each group. The group's buttons act only on these; the keys too, see App. */
export function GroupsView({
  groups,
  loading,
  roles,
  dock,
  labelText,
  onName,
  onNew,
  focus,
  setFocus,
  firstRun,
  picked,
  setPicked,
  episode,
  progress,
  work,
}: GroupsViewProps) {
  /* The last line ticked in each group, so Shift+click can tick the lines between. */
  const [anchor, setAnchor] = useState<Record<number, string>>({});
  /* Groups stay put while labeling, so a group whose lines are all labeled no longer counts as left. */
  const left = groups.filter((g) => g.clips.some((c) => !c.label)).length;
  if (loading)
    return (
      <Empty>
        <Spinner className="mx-auto size-6" />
        <p>{tr("正在把声音相近的台词分组…", "Grouping lines with similar voices…")}</p>
      </Empty>
    );
  return (
    <div>
      {/* The episode's summary, kept on screen while scrolling like the one in Scenes. -top-2 cancels the top
          padding of the list, so cards don't show through above it. */}
      <div className="sticky -top-2 z-[3] flex flex-wrap items-center gap-2.5 border-b bg-background px-1 pt-3 pb-2">
        <h2 className="text-base font-semibold">{episode}</h2>
        <EpisodeProgress progress={progress} />
        <Tip
          text={tr(
            "只给要处理的台词分组，跟「场景」里「只看要处理的」是同一批。机器有把握的在「角色」里核对",
            'Only lines still to do are grouped, the same lines as "Only to do" in Scenes. Lines the machine is confident about are checked in Characters',
          )}
        >
          <span className="text-xs text-muted-foreground">
            {tr(`还剩 ${left} 组`, `${many(left, "group")} left`)}
          </span>
        </Tip>
      </div>
      {firstRun && (
        <Welcome
          title={tr("第一步：给声音相近的一组起个名字", "Step one: name a group of similar voices")}
        >
          <p>
            {tr(
              "机器先把听起来像同一个人的台词放在一起。点一句听一听，勾上同一个人的台词，或者按「全选」。再在下面选是谁：是你要收集的新面孔，就按「新角色」把勾上的台词定成一个目标角色，接着可以起名字、从画面里截一张头像，都可以以后再做；不是你要的人，就按「其他」。",
              'The machine puts lines that sound like the same person together. Click a line to hear it, then tick the lines of the same person, or press "Select all". Then pick who it is below: if it is a new face you want to collect, press "New character" to make the ticked lines a target character, then you can type a name and crop an avatar from the picture, or do both later. If it is not someone you want, press "Other".',
            )}
          </p>
          <ol className="mt-1.5 list-decimal pl-[18px]">
            <li>
              {withKeys(
                tr(
                  "一组里混着几个人时，分几次勾、几次标。按住 [Shift] 点，能一下勾上中间的几句。",
                  "When a group mixes several people, tick and label them in turns. [Shift]+click ticks all the lines in between.",
                ),
              )}
            </li>
            <li>
              {withKeys(
                tr(
                  "有勾选时，[1]–[9]、[Q]、[N] 标勾上的台词；没勾选时，标正在播放的那一句。",
                  "While lines are ticked, [1]–[9], [Q] and [N] label the ticked lines; with none ticked, they label the line playing.",
                ),
              )}
            </li>
            <li>
              {tr(
                "每命名一组，机器就会重新学一次，其余台词的猜测随之变准。",
                "Each group you name retrains the machine, and its guesses for the other lines get better.",
              )}
            </li>
            <li>
              {tr(
                "定下目标角色、再标几组「其他」以后，去「场景」视图逐句确认会快得多。",
                'Once you have your target characters and a few groups of "Other", confirming line by line in the Scenes view goes much faster.',
              )}
            </li>
          </ol>
        </Welcome>
      )}
      {/* Says why there is nothing to do here, then where the work goes on. Wider than usual, so each step fits on one line when there is room. */}
      {groups.length === 0 && (
        <Empty
          title={tr("「起步分组」里没有要做的了", "No more work to do in Groups")}
          className="max-w-4xl"
        >
          <p>
            {progress.auto > 0
              ? tr(
                  "你标的已经够机器学了，它替你做了大部分判断。下一步：",
                  "You have labeled enough for the machine to learn from, and it has made most of the calls. Next:",
                )
              : tr("下一步：", "Next:")}
          </p>
          <ol className="mx-auto mt-1.5 w-fit list-decimal pl-[18px] text-left">
            {work > 0 && (
              <li>
                {withKeys(
                  tr(
                    `去「场景」，按 [F] 只看要处理的，确认剩下的 ${work} 句`,
                    `In Scenes, press [F] for Only to do and confirm the ${lines(work)} left`,
                  ),
                )}
                {/* Why these lines are not here as a group. */}
                <div className="text-xs">
                  {work === 1
                    ? tr(
                        "一句成不了组：分组要至少两句听起来像同一个人",
                        "One line can't make a group: a group needs at least two lines that sound like the same person",
                      )
                    : tr(
                        "它们分不成组：彼此听起来不像，或者特征不够",
                        "They can't be grouped: they don't sound alike, or have too little voice to tell",
                      )}
                </div>
              </li>
            )}
            {progress.auto > 0 && (
              <li>
                {withKeys(
                  tr(
                    "去「角色」，逐个角色核对机器的判断：改掉错的，其余按 [Shift]+[Enter] 一起确认",
                    "In Characters, check what the machine gave each character: fix the wrong ones, then confirm the rest with [Shift]+[Enter]",
                  ),
                )}
              </li>
            )}
            <li>{tr("够用了就去「导出」", "When you have enough, go to Export")}</li>
          </ol>
        </Empty>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-3.5 pt-3">
        {groups.map((g, gi) => {
          const ticked = picked[g.key] || new Set<string>();
          /* Labeled lines stay in the group for you to see, but can't be ticked. */
          const open = g.clips.filter((c) => !c.label);
          const keep = open.filter((c) => ticked.has(c.id));
          const all = open.length > 0 && keep.length === open.length;
          const done = open.length === 0;
          /* Built on the newest ticks, so two clicks before the page draws again both count. */
          const tick = (c: Clip, e: MouseEvent) => {
            e.stopPropagation();
            const shift = e.shiftKey;
            setPicked((p) => {
              const next = new Set(p[g.key] || []);
              const on = !next.has(c.id);
              const from = open.findIndex((o) => o.id === anchor[g.key]);
              const to = open.findIndex((o) => o.id === c.id);
              const span =
                shift && from >= 0 ? open.slice(Math.min(from, to), Math.max(from, to) + 1) : [c];
              span.forEach((o) => (on ? next.add(o.id) : next.delete(o.id)));
              return { ...p, [g.key]: next };
            });
            setAnchor((a) => ({ ...a, [g.key]: c.id }));
          };
          const tickAll = () =>
            setPicked((p) => ({ ...p, [g.key]: new Set(all ? [] : open.map((c) => c.id)) }));
          const ids = keep.map((c) => c.id);
          return (
            <Card key={g.key} className={cn("gap-2.5 p-3.5", done && "opacity-60")}>
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                {tr(`第 ${gi + 1} 组`, `Group ${gi + 1}`)}
                <span className="text-xs font-normal text-muted-foreground">
                  {lines(g.size)} · {tr(`${g.seconds} 秒`, `${g.seconds} s`)}
                  {done ? tr(" · 都标好了", " · all labeled") : ""}
                </span>
                {g.hint && <Closest roles={roles} name={g.hint.name} title={GUESSED_MOST()} />}
              </h3>
              {/* Columns: tick box (blank once labeled), text, label, time. */}
              <div className="flex max-h-[210px] flex-col gap-0.5 overflow-y-auto">
                {g.clips.map((c) => (
                  <div
                    key={c.id}
                    className={cn(
                      "grid grid-cols-[28px_1fr_auto_auto] items-center gap-2 rounded-md border border-transparent px-1.5 py-[3px] text-[13px] hover:bg-muted/60",
                      c.id === focus && SELECTED_ROW,
                    )}
                    onClick={() => setFocus(c.id)}
                  >
                    {c.label ? (
                      <span></span>
                    ) : (
                      /* The tick box only selects; the rest of the row plays the line. The whole left end
                         of the row, top to bottom, counts as the box, so it is easy to hit; only this part
                         shows the hand and its own hover color, so it is clear where it ends. */
                      <span
                        className="-my-[3px] -ml-1.5 flex cursor-pointer items-center justify-center self-stretch rounded-l-md pl-1.5 hover:bg-muted"
                        onClick={(e) => tick(c, e)}
                        onMouseDown={(e) => e.preventDefault()}
                      >
                        <Checkbox
                          aria-label={c.text}
                          checked={ticked.has(c.id)}
                          className="pointer-events-none"
                        />
                      </span>
                    )}
                    <span
                      className={cn(
                        ticked.has(c.id) && !c.label && "font-semibold",
                        c.label && "text-muted-foreground",
                      )}
                    >
                      {c.text || tr("（没有字幕文字）", "(no subtitle text)")}
                    </span>
                    {c.label ? (
                      <Tag
                        look="done"
                        tip={withKeys(
                          tr(
                            "已经标了；按 [Z] 撤销，或在左边改",
                            "Already labeled. Press [Z] to undo, or change it on the left",
                          ),
                        )}
                      >
                        {labelText[c.label] || c.label}
                        {c.unusable ? tr("·质量低", " · low quality") : ""}
                      </Tag>
                    ) : (
                      <span></span>
                    )}
                    <span className="text-[11px] text-muted-foreground tabular-nums">
                      {c.episode} {stamp(c.start)}
                    </span>
                  </div>
                ))}
              </div>
              {!done && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <Button variant="outline" size="sm" onClick={tickAll}>
                    {all ? tr("全不选", "Select none") : tr("全选", "Select all")}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {keep.length
                      ? withKeys(
                          tr(
                            `勾了 ${keep.length} 句；[1]–[9]、[Q]、[N] 也标勾上的`,
                            `${lines(keep.length)} ticked; [1]–[9], [Q] and [N] label them too`,
                          ),
                        )
                      : tr(
                          "先勾上同一个人的台词，再选是谁",
                          "Tick the lines of one person first, then pick who it is",
                        )}
                  </span>
                </div>
              )}
              {/* The same choices in the same order as the bottom bar, with the same keys. */}
              {!done && (
                <div className="flex flex-wrap gap-1.5">
                  {dock.map((name, i) => (
                    <Chip
                      key={name}
                      small
                      top={name === g.hint?.name}
                      off={!keep.length}
                      tip={name === g.hint?.name && GUESSED_MOST()}
                      onPick={() => onName(ids, name)}
                      picture={<Avatar role={roles[name]} name={name} size="sm" />}
                      hotkey={i < 9 ? String(i + 1) : undefined}
                      extra={
                        <LowButton
                          disabled={!keep.length}
                          tip={lowTip()}
                          hotkey={i < 9 ? i + 1 : undefined}
                          onClick={() => onName(ids, name, true)}
                        />
                      }
                    >
                      <RoleName role={roles[name]} name={name} />
                    </Chip>
                  ))}
                  <Chip
                    small
                    off={!keep.length}
                    tip={tr("不是任何一个目标角色", "Not any of the target characters")}
                    onPick={() => onName(ids, OTHER)}
                    picture={<Avatar blank size="sm" />}
                    hotkey="Q"
                  >
                    {labelText[OTHER]}
                  </Chip>
                  <Chip
                    small
                    off={!keep.length}
                    tip={tr(
                      "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
                      "Make a new target character; you can name it later. With video, crop an avatar next",
                    )}
                    onPick={() => onNew(ids)}
                    picture={<Avatar plus size="sm" />}
                    hotkey="N"
                  >
                    {tr("新角色", "New character")}
                  </Chip>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
