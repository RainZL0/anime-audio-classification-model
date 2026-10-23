import type { Clip, Counts as RoleCounts, Role, Roles, Summary } from "../api";
import { confirmedOf, maybeListOf, OTHER, pendingOf, type LabelText } from "../clips";
import { Avatar } from "../components/Avatar";
import { RoleName } from "../components/RoleName";
import { Row } from "../components/Row";
import { howLong } from "../format";
import { lines, tr } from "../language";

/* ───────────── Characters view: check the machine's calls per character ───────────── */

/* The numbers on the right of a character row: lines confirmed, lines the machine gave them, and below,
   the total length of the confirmed lines. */
function Counts({ info }: { info: RoleCounts }) {
  return (
    <span className="c">
      {info.confirmed}
      {info.predicted ? (
        <>
          {" "}
          · <b>{info.predicted}</b>
        </>
      ) : (
        ""
      )}
      {info.seconds > 0 && (
        <>
          <br />
          <span title={tr("确认过的台词累计时长", "Total length of confirmed lines")}>
            {howLong(info.seconds)}
          </span>
        </>
      )}
    </span>
  );
}

interface RoleViewProps {
  state: Summary;
  roles: Roles;
  labelText: LabelText;
  role: string | null;
  setRole: (name: string) => void;
  clips: Clip[];
  focus: string | null;
  setFocus: (id: string) => void;
  onConfirmRest: () => void;
  onRename: () => void;
  onToggleTarget: () => void;
  onAvatar: () => void;
  canCrop: boolean;
  flashes: Set<string>;
  playing: boolean;
  setPlaying: (on: boolean) => void;
}

export function RoleView({
  state,
  roles,
  labelText,
  role,
  setRole,
  clips,
  focus,
  setFocus,
  onConfirmRest,
  onRename,
  onToggleTarget,
  onAvatar,
  canCrop,
  flashes,
  playing,
  setPlaying,
}: RoleViewProps) {
  const list = state.roles;
  const other = role === OTHER;
  /* "Other" has no entry of its own, so it gets an empty one. */
  const current: Partial<Role> | undefined = other ? {} : role ? roles[role] : undefined;
  const info: RoleCounts | undefined = other ? state.other : list.find((r) => r.name === role);
  const name = other ? labelText[OTHER] : role;
  const pending = pendingOf(clips);
  const maybe = maybeListOf(clips);
  const confirmed = confirmedOf(clips, role);
  /* Who the machine gave these lines to, as written inside a sentence. */
  const them = other ? tr("「其他」", '"Other"') : role;
  const row = (clip: Clip, extra: { maybeOf?: string; showTarget?: boolean }) => (
    <Row
      key={clip.id}
      clip={clip}
      roles={roles}
      labelText={labelText}
      selected={clip.id === focus}
      flash={flashes.has(clip.id)}
      onSelect={() => setFocus(clip.id)}
      {...extra}
    />
  );
  return (
    <div className="roles-grid">
      <div className="role-list">
        {list.map((r) => (
          <div
            key={r.name}
            className={`role-item ${r.name === role ? "on" : ""} ${r.target ? "" : "off"}`}
            onClick={() => setRole(r.name)}
            title={
              r.target
                ? ""
                : tr(
                    "不是目标角色：机器不再猜这个角色，已有的标签照样留着",
                    "Not a target character: the machine no longer guesses them, their labels stay",
                  )
            }
          >
            <Avatar role={r} name={r.name} size="md" />
            <RoleName role={r} name={r.name} cls="nm" />
            <Counts info={r} />
          </div>
        ))}
        <div
          className={`role-item other ${other ? "on" : ""}`}
          onClick={() => setRole(OTHER)}
          title={tr("不是任何一个目标角色", "Not any of the target characters")}
        >
          <Avatar blank={true} size="md" />
          <span className="rn nm">{labelText[OTHER]}</span>
          <Counts info={state.other} />
        </div>
      </div>
      <div>
        {!current || !role ? (
          <div className="empty">
            <h2>{tr("选一个角色", "Pick a character")}</h2>
            <p>
              {tr(
                "左边上面是目标角色，就是你要收集的人；其余的人一律标「其他」。灰色数字是确认过的句数，橙色是机器归进来、还没人确认的句数，下面是确认过的台词累计多长。",
                'At the top left are the target characters, the people you want to collect; everyone else is labeled "Other". The gray number is lines confirmed, the orange one is lines the machine gave them that no one has confirmed yet, and below is the total length of the confirmed lines.',
              )}
            </p>
          </div>
        ) : (
          <>
            <div className="role-head">
              {other ? (
                <Avatar blank={true} size="xl" />
              ) : (
                <Avatar
                  role={current as Role}
                  name={role}
                  size="xl"
                  onClick={canCrop ? onAvatar : null}
                  title={
                    canCrop
                      ? tr(
                          "从左边的画面里截一块当头像",
                          "Crop an avatar from the picture on the left",
                        )
                      : tr(
                          "左边放出画面后，可以从画面里截头像",
                          "Once the picture on the left shows, you can crop an avatar from it",
                        )
                  }
                />
              )}
              <div>
                <h2>{other ? name : <RoleName role={current as Role} name={role} />}</h2>
                <div className="stats">
                  {tr(`确认过 ${confirmed.length} 句`, `${lines(confirmed.length)} confirmed`)}
                  {info && info.seconds > 0
                    ? tr(`，共 ${howLong(info.seconds)}`, `, ${howLong(info.seconds)} in total`)
                    : ""}
                  {info && info.low_seconds > 0
                    ? tr(
                        `，其中质量低 ${howLong(info.low_seconds)}`,
                        `, ${howLong(info.low_seconds)} of it low quality`,
                      )
                    : ""}{" "}
                  ·{" "}
                  {tr(
                    `机器归进来 ${pending.length} 句`,
                    `${lines(pending.length)} given by the machine`,
                  )}
                  {other || current.target
                    ? ""
                    : tr(" · 不是目标角色", " · not a target character")}
                </div>
              </div>
              <div className="role-actions">
                <button onClick={() => setPlaying(!playing)}>
                  {playing ? tr("停止连播", "Stop playing") : tr("连播待核对", "Play all to check")}{" "}
                  <kbd>P</kbd>
                </button>
                {!other && (
                  <>
                    <button className={current.named === false ? "primary" : ""} onClick={onRename}>
                      {current.named === false
                        ? tr("起名字", "Name")
                        : tr("改名或合并", "Rename or merge")}
                    </button>
                    <button
                      onClick={onToggleTarget}
                      title={
                        current.target
                          ? tr(
                              "不再收集这个人：机器不再猜这个角色，已标的留着，以后还能加回来",
                              "Stop collecting this person: the machine stops guessing them, their labels stay, and you can add them back later",
                            )
                          : tr(
                              "重新收集这个人：以前标「其他」的台词会列进「可能漏掉的」，要复查",
                              'Collect this person again: lines labeled "Other" before will be listed under Maybe missed for you to recheck',
                            )
                      }
                    >
                      {current.target
                        ? tr("不再作为目标", "Stop targeting")
                        : tr("设为目标角色", "Make target")}
                    </button>
                  </>
                )}
              </div>
            </div>
            {pending.length > 0 && (
              <div className="welcome" style={{ alignItems: "center" }}>
                <div style={{ flex: 1 }}>
                  <h3>
                    {tr(
                      `机器把这 ${pending.length} 句归给了${other ? "「其他」" : ` ${role}`}`,
                      `The machine gave these ${lines(pending.length)} to ${them}`,
                    )}
                  </h3>
                  <p>
                    {tr(
                      <>
                        从最没把握的开始排。听到不对的，直接标成对的人或「其他」<kbd>Q</kbd>
                        ，它就离开这里；听完一键确认其余的。
                      </>,
                      <>
                        Least sure first. When one is wrong, label it with the right character or
                        "Other" <kbd>Q</kbd> and it leaves this list; when you're done listening,
                        confirm the rest at once.
                      </>,
                    )}
                  </p>
                </div>
                <button className="primary" onClick={onConfirmRest}>
                  {tr(
                    `确认其余 ${pending.length} 句`,
                    `Confirm the other ${lines(pending.length)}`,
                  )}{" "}
                  <kbd style={{ marginLeft: "4px" }}>Shift+Enter</kbd>
                </button>
              </div>
            )}
            {pending.map((clip) => row(clip, { showTarget: other }))}
            {maybe.length > 0 && (
              <>
                <div className="section-title">
                  {tr(`可能漏掉的 ${maybe.length} 句`, `Maybe missed: ${lines(maybe.length)}`)}
                </div>
                <p className="note" style={{ margin: "0 0 8px" }}>
                  {tr(
                    `机器没归给 ${role}，但听起来有可能是，最像的排在前面。刚设成目标角色时，以前标成「其他」的台词也会列在这里。`,
                    `The machine didn't give these to ${role}, but they might be; most likely first. Right after you make someone a target, lines labeled "Other" before are listed here too.`,
                  )}
                </p>
                {maybe.map((clip) => row(clip, { maybeOf: role }))}
              </>
            )}
            {confirmed.length > 0 && (
              <>
                <div className="section-title">
                  {tr(`确认过的 ${confirmed.length} 句`, `Confirmed: ${lines(confirmed.length)}`)}
                  {other
                    ? tr("，最像某个目标角色的排在前面", ", most like a target character first")
                    : ""}
                </div>
                {confirmed.map((clip) => row(clip, { showTarget: other }))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
