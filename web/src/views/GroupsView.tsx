import { useState, type MouseEvent } from "react";
import type { Clip, Group, Roles } from "../api";
import { lowTip, OTHER, type LabelText } from "../clips";
import { Avatar } from "../components/Avatar";
import { Closest } from "../components/Pills";
import { RoleName } from "../components/RoleName";
import { stamp } from "../format";
import { lines, tr } from "../language";

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
}

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
}: GroupsViewProps) {
  /* The last line ticked in each group, so Shift+click can tick the lines between. */
  const [anchor, setAnchor] = useState<Record<number, string>>({});
  if (loading)
    return (
      <div className="empty">
        <div className="spinner" style={{ margin: "auto" }}></div>
        <p>{tr("正在把声音相近的台词分组…", "Grouping lines with similar voices…")}</p>
      </div>
    );
  return (
    <div>
      {firstRun && (
        <div className="welcome">
          <div>
            <h3>
              {tr("第一步：给声音相近的一组起个名字", "Step one: name a group of similar voices")}
            </h3>
            <p>
              {tr(
                "机器先把听起来像同一个人的台词放在一起。点一句听一听，勾上同一个人的台词，或者按「全选」。再在下面选是谁：是你要收集的新面孔，就按「新角色」把勾上的台词定成一个目标角色，接着可以起名字、从画面里截一张头像，都可以以后再做；不是你要的人，就按「其他」。",
                'The machine puts lines that sound like the same person together. Click a line to hear it, then tick the lines of the same person, or press "Select all". Then pick who it is below: if it is a new face you want to collect, press "New character" to make the ticked lines a target character, then you can type a name and crop an avatar from the picture, or do both later. If it is not someone you want, press "Other".',
              )}
            </p>
            <ol>
              <li>
                {tr(
                  "一组里混着几个人时，分几次勾、几次标。按住 Shift 点，能一下勾上中间的几句。",
                  "When a group mixes several people, tick and label them in turns. Shift+click ticks all the lines in between.",
                )}
              </li>
              <li>
                {tr(
                  "有勾选时，数字键、Q、N 标勾上的台词；没勾选时，标正在播放的那一句。",
                  "While lines are ticked, the number keys, Q and N label the ticked lines; with none ticked, they label the line playing.",
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
          </div>
        </div>
      )}
      {groups.length === 0 && (
        <div className="empty">
          <h2>{tr("没有可分的组了", "No groups left")}</h2>
          <p>
            {tr(
              "这一集还没标的台词，要么彼此都不太像，要么已经全部有了名字。去「场景」视图逐句确认吧。",
              "The unlabeled lines in this episode are either not much alike, or all named already. Go confirm them line by line in the Scenes view.",
            )}
          </p>
        </div>
      )}
      <div className="groups">
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
            <div
              key={g.key}
              className={`group ${g.clips.some((c) => c.id === focus) ? "sel" : ""} ${done ? "done" : ""}`}
            >
              <h3>
                {tr(`第 ${gi + 1} 组`, `Group ${gi + 1}`)}{" "}
                <span className="meta">
                  {lines(g.size)} · {tr(`${g.seconds} 秒`, `${g.seconds} s`)}
                  {done ? tr(" · 都标好了", " · all labeled") : ""}
                </span>
                {g.hint && (
                  <Closest
                    roles={roles}
                    name={g.hint.name}
                    title={tr(
                      "机器在这组里最常猜的角色",
                      "The character the machine guesses most often in this group",
                    )}
                  />
                )}
              </h3>
              <div className="members">
                {g.clips.map((c) => (
                  <div
                    key={c.id}
                    className={`member ${ticked.has(c.id) && !c.label ? "picked" : ""} ${c.label ? "labeled" : ""} ${c.id === focus ? "playing" : ""}`}
                    onClick={() => setFocus(c.id)}
                  >
                    {c.label ? (
                      <span></span>
                    ) : (
                      /* readOnly only tells React the click below changes it; a box can still be ticked. */
                      <input
                        type="checkbox"
                        checked={ticked.has(c.id)}
                        readOnly
                        onClick={(e) => tick(c, e)}
                        onMouseDown={(e) => e.preventDefault()}
                        title={tr(
                          "勾上，下面的按钮就标这一句；按住 Shift 点，勾上中间的几句",
                          "Tick it for the buttons below to label it; Shift+click ticks the lines in between",
                        )}
                      />
                    )}
                    <span>{c.text || tr("（没有字幕文字）", "(no subtitle text)")}</span>
                    {c.label ? (
                      <span
                        className="pill done"
                        title={tr(
                          "已经标了；按 Z 撤销，或在左边改",
                          "Already labeled. Press Z to undo, or change it on the left",
                        )}
                      >
                        {labelText[c.label] || c.label}
                        {c.unusable ? tr("·质量低", " · low quality") : ""}
                      </span>
                    ) : (
                      <span></span>
                    )}
                    <span className="t">
                      {c.episode} {stamp(c.start)}
                    </span>
                  </div>
                ))}
              </div>
              {!done && (
                <div className="pick-row">
                  <button type="button" onClick={tickAll}>
                    {all ? tr("全不选", "Select none") : tr("全选", "Select all")}
                  </button>
                  <span className="note">
                    {keep.length
                      ? tr(
                          `勾了 ${keep.length} 句；数字键、Q、N 也标勾上的`,
                          `${lines(keep.length)} ticked; number keys, Q and N label them too`,
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
                <div className="who-row">
                  {dock.map((name, i) => (
                    <div
                      key={name}
                      className={`chip ${name === g.hint?.name ? "top" : ""} ${keep.length ? "" : "off"}`}
                      title={
                        name === g.hint?.name
                          ? tr(
                              "机器在这组里最常猜的角色",
                              "The character the machine guesses most often in this group",
                            )
                          : ""
                      }
                      onClick={() => keep.length && onName(ids, name)}
                    >
                      <Avatar role={roles[name]} name={name} size="sm" />
                      <RoleName role={roles[name]} name={name} />
                      {i < 9 ? <span className="k">{i + 1}</span> : ""}
                      <button
                        type="button"
                        className="low"
                        disabled={!keep.length}
                        title={
                          tr(`标成 ${name}·质量低：`, `Label as ${name}, low quality: `) + lowTip()
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          onName(ids, name, true);
                        }}
                      >
                        {tr("质量低", "Low quality")}
                        {i < 9 ? <span className="k"> ⇧{i + 1}</span> : ""}
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="chip"
                    disabled={!keep.length}
                    onClick={() => onName(ids, OTHER)}
                    title={tr("不是你要收集的人", "Not someone you want to collect")}
                  >
                    <Avatar blank={true} size="sm" />
                    <span className="rn">{labelText[OTHER]}</span>
                    <span className="k">Q</span>
                  </button>
                  <button
                    type="button"
                    className="chip"
                    disabled={!keep.length}
                    onClick={() => onNew(ids)}
                    title={tr(
                      "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
                      "Make a new target character; you can name it later. With video, crop an avatar next",
                    )}
                  >
                    <div className="av sm unknown">+</div>
                    <span className="rn">{tr("新角色", "New character")}</span>
                    <span className="k">N</span>
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
