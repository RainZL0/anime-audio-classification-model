import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import type { Clip, Counts as RoleCounts, Role, Roles, Summary } from "../api";
import { confirmedOf, maybeListOf, OTHER, pendingOf, type LabelText } from "../clips";
import { Avatar } from "../components/Avatar";
import { Empty, Note } from "../components/Notes";
import { RoleName } from "../components/RoleName";
import { Row } from "../components/Row";
import { Tip } from "../components/Tip";
import { howLong } from "../format";
import { lines, tr } from "../language";

/* ───────────── Characters view: check the machine's calls per character ───────────── */

/* The numbers on the right of a character row: lines confirmed, lines the machine gave them, and below,
   the total length of the confirmed lines. */
function Counts({ info }: { info: RoleCounts }) {
  return (
    <span className="text-right text-[11px] text-muted-foreground tabular-nums">
      {info.confirmed}
      {info.predicted ? (
        <>
          {" "}
          · <b className="font-semibold text-warning">{info.predicted}</b>
        </>
      ) : (
        ""
      )}
      {info.seconds > 0 && (
        <>
          <br />
          <Tip text={tr("确认过的台词累计时长", "Total length of confirmed lines")}>
            <span>{howLong(info.seconds)}</span>
          </Tip>
        </>
      )}
    </span>
  );
}

/* One row of the character list on the left. */
const ITEM =
  "grid grid-cols-[auto_1fr_auto] items-center gap-x-3 rounded-lg border border-transparent px-2 py-1.5 hover:bg-muted/60";
const ITEM_ON = "border-primary/40 bg-accent hover:bg-accent";

/* A short gray heading above a part of the list. */
const SECTION_TITLE = "mx-1 mt-[18px] mb-1.5 text-xs text-muted-foreground";

/* The id of the maybe-missed list, which the line at the top jumps to. */
const MAYBE = "maybe-missed";

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
      showEpisode
      {...extra}
    />
  );
  /* The list on the left is as wide as its longest row, up to 230px. When the list side of the page is narrow
     (the divider can make it so), the list goes on top as a row of characters instead. */
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-[18px] pt-2.5 @max-xl:grid-cols-1">
      {/* Characters that are not targets are listed under the target characters, with a lighter name. "Other"
          goes at the very bottom, with a divider line above it. */}
      <div className="sticky top-2 flex max-h-[calc(100vh-170px)] w-max max-w-[230px] min-w-40 flex-col gap-0.5 self-start overflow-y-auto @max-xl:static @max-xl:max-h-none @max-xl:w-auto @max-xl:max-w-none @max-xl:flex-row @max-xl:flex-wrap">
        {list.map((r) => (
          <Tip
            key={r.name}
            text={
              r.target
                ? ""
                : tr(
                    "不是目标角色：机器不再猜这个角色，已有的标签照样留着",
                    "Not a target character: the machine no longer guesses them, their labels stay",
                  )
            }
          >
            <div className={cn(ITEM, r.name === role && ITEM_ON)} onClick={() => setRole(r.name)}>
              <Avatar role={r} name={r.name} size="md" />
              <RoleName
                role={r}
                name={r.name}
                className={cn(!r.target && "text-muted-foreground")}
              />
              <Counts info={r} />
            </div>
          </Tip>
        ))}
        <Separator className="my-1 @max-xl:hidden" />
        <Tip text={tr("不是任何一个目标角色", "Not any of the target characters")}>
          <div className={cn(ITEM, other && ITEM_ON)} onClick={() => setRole(OTHER)}>
            <Avatar blank={true} size="md" />
            <span>{labelText[OTHER]}</span>
            <Counts info={state.other} />
          </div>
        </Tip>
      </div>
      <div>
        {!current || !role ? (
          <Empty title={tr("选一个角色", "Pick a character")}>
            <p>
              {tr(
                "左边上面是目标角色，就是你要收集的人；其余的人一律标「其他」。灰色数字是确认过的句数，橙色是机器归进来、还没人确认的句数，下面是确认过的台词累计多长。",
                'At the top left are the target characters, the people you want to collect; everyone else is labeled "Other". The gray number is lines confirmed, the orange one is lines the machine gave them that no one has confirmed yet, and below is the total length of the confirmed lines.',
              )}
            </p>
          </Empty>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3.5 pt-1.5 pb-3">
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
              <div className="min-w-48 flex-1">
                <h2 className="text-xl font-semibold">
                  {other ? name : <RoleName role={current as Role} name={role} />}
                </h2>
                <div className="text-xs text-muted-foreground">
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
                  {/* The maybe-missed list comes after every line the machine gave them, often far down the
                      page, so the top says it is there and jumps to it. */}
                  {maybe.length > 0 && (
                    <>
                      {" · "}
                      <button
                        type="button"
                        className="text-warning underline underline-offset-2 hover:text-foreground"
                        onClick={() =>
                          document
                            .getElementById(MAYBE)
                            ?.scrollIntoView({ behavior: "smooth", block: "start" })
                        }
                      >
                        {tr(
                          `另有 ${maybe.length} 句可能漏掉`,
                          `${lines(maybe.length)} maybe missed`,
                        )}
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => setPlaying(!playing)}>
                  {playing ? tr("停止连播", "Stop playing") : tr("连播待核对", "Play all to check")}{" "}
                  <Kbd>P</Kbd>
                </Button>
                {!other && (
                  <>
                    <Button
                      variant={current.named === false ? "default" : "outline"}
                      onClick={onRename}
                    >
                      {current.named === false
                        ? tr("起名字", "Name")
                        : tr("改名或合并", "Rename or merge")}
                    </Button>
                    <Tip
                      text={
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
                      <Button variant="outline" onClick={onToggleTarget}>
                        {current.target
                          ? tr("不再作为目标", "Stop targeting")
                          : tr("设为目标角色", "Make target")}
                      </Button>
                    </Tip>
                  </>
                )}
              </div>
            </div>
            {/* The button goes under the text when there is not room for both side by side. */}
            {pending.length > 0 && (
              <div className="my-3 flex flex-wrap items-center gap-3.5 rounded-xl border bg-muted/50 px-4 py-3.5">
                <div className="min-w-0 flex-[1_1_16rem]">
                  <h3 className="mb-1 text-sm font-semibold">
                    {tr(
                      `机器把这 ${pending.length} 句归给了${other ? "「其他」" : ` ${role}`}`,
                      `The machine gave these ${lines(pending.length)} to ${them}`,
                    )}
                  </h3>
                  <p className="text-[13px] text-muted-foreground">
                    {tr(
                      <>
                        从最没把握的开始排。听到不对的，直接标成对的人或「其他」<Kbd>Q</Kbd>
                        ，它就离开这里；听完一键确认其余的。
                      </>,
                      <>
                        Least sure first. When one is wrong, label it with the right character or
                        "Other" <Kbd>Q</Kbd> and it leaves this list; when you're done listening,
                        confirm the rest at once.
                      </>,
                    )}
                  </p>
                </div>
                <Button onClick={onConfirmRest}>
                  {tr(
                    `确认其余 ${pending.length} 句`,
                    `Confirm the other ${lines(pending.length)}`,
                  )}{" "}
                  <Kbd className="ml-1">Shift+Enter</Kbd>
                </Button>
              </div>
            )}
            {pending.map((clip) => row(clip, { showTarget: other }))}
            {maybe.length > 0 && (
              <>
                <div id={MAYBE} className={cn(SECTION_TITLE, "scroll-mt-4")}>
                  {tr(`可能漏掉的 ${maybe.length} 句`, `Maybe missed: ${lines(maybe.length)}`)}
                </div>
                <Note className="mb-2">
                  {tr(
                    `机器没归给 ${role}，但听起来有可能是，最像的排在前面。刚设成目标角色时，以前标成「其他」的台词也会列在这里。`,
                    `The machine didn't give these to ${role}, but they might be; most likely first. Right after you make someone a target, lines labeled "Other" before are listed here too.`,
                  )}
                </Note>
                {maybe.map((clip) => row(clip, { maybeOf: role }))}
              </>
            )}
            {confirmed.length > 0 && (
              <>
                <div className={SECTION_TITLE}>
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
