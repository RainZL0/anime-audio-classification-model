import { useEffect, useRef, useState, type FormEvent } from "react";
import { call, type Adding, type Check, type Summary, type SubtitleStyles as Styles } from "../api";
import { minutes } from "../format";
import { lines, many, tr } from "../language";
import type { Toast } from "../toast";

/* ───────────── Adding an episode ───────────── */

/* The machine checks, the same list as `avoc doctor`. Fetched once; torch is loaded for the GPU check, so it can
   take a few seconds. */
export function Checks() {
  const [list, setList] = useState<Check[] | null>(null);
  useEffect(() => {
    call<Check[]>("/api/doctor")
      .then(setList)
      .catch(() => setList([]));
  }, []);
  if (!list) return <div className="note">{tr("正在检查这台机器…", "Checking this machine…")}</div>;
  return (
    <ul className="checks">
      {list.map((c) => (
        <li key={c.text} className={c.ok ? "ok" : c.required ? "bad" : "soft"}>
          <span className="mark">{c.ok ? "✓" : c.required ? "✗" : "–"}</span>
          <span>
            {c.text}
            {!c.ok && c.fix ? (
              <>
                <br />
                <span className="note">{c.fix}</span>
              </>
            ) : (
              ""
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* null: no subtitle path yet. {}: reading. Otherwise the server's description, or {error}. */
type Found = (Partial<Styles> & { error?: string }) | null;

/* What the server read from the dialogue subtitles: the text encoding, and the styles (the named looks an ASS file
   gives its lines, such as "Default" or "OP"). The ticked styles are cut into clips; they start as the ones picked
   automatically. With a single style there is nothing to choose, so only the line count is shown. */
function SubtitleStyles({
  found,
  chosen,
  setChosen,
}: {
  found: NonNullable<Found>;
  chosen: Set<string>;
  setChosen: (next: Set<string>) => void;
}) {
  /* Subtitle groups often give each sign its own style with a line or two, so only the ticked styles and the next
     few biggest are shown at first. */
  const [all, setAll] = useState(false);
  if (found.error) return <div className="note warn">{found.error}</div>;
  if (!found.styles)
    return <div className="note">{tr("正在读字幕…", "Reading the subtitles…")}</div>;
  const format = (found.format ?? "").toUpperCase();
  const read = tr(`${format}，${found.encoding}`, `${format}, ${found.encoding}`);
  if (found.styles.length === 0)
    return (
      <div className="note warn">
        {tr(`字幕里没有台词（${read}）`, `There are no dialogue lines in the subtitles (${read})`)}
      </div>
    );
  /* Marks such as speaker names that the text cleaning does not know, found in the picked styles. */
  const marked = found.marked && <div className="note warn">{found.marked}</div>;
  if (found.styles.length === 1)
    return (
      <>
        <div className="note">
          {tr(
            `读到 ${found.styles[0].lines} 句台词（${read}）`,
            `Read ${lines(found.styles[0].lines)} of dialogue (${read})`,
          )}
        </div>
        {marked}
      </>
    );
  const toggle = (name: string) => {
    const next = new Set(chosen);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setChosen(next);
  };
  const automatic = found.picked ?? [];
  /* Ordered by the automatic choice, not the ticks, so a row stays put when it is clicked. */
  const picked = (s: { name: string }) => Number(automatic.includes(s.name));
  const ordered = [...found.styles].sort((a, b) => picked(b) - picked(a) || b.lines - a.lines);
  const shown = all
    ? ordered
    : ordered.filter((s, i) => chosen.has(s.name) || i < automatic.length + 3);
  const hidden = ordered.filter((s) => !shown.includes(s));
  const hiddenLines = hidden.reduce((n, s) => n + s.lines, 0);
  return (
    <div className="style-list">
      <div className="note">
        {tr(
          `字幕（${read}）里的台词分几种样式。勾上的切成片段；歌词、招牌字之类的不用勾。已经自动选好，一般不用改，看看例句对不对就行。`,
          `The lines in these subtitles (${read}) come in several styles. Ticked styles are cut into clips; leave out song lyrics, signs and such. They are already picked automatically and rarely need changing; just check the sample lines.`,
        )}
      </div>
      {shown.map((s) => (
        <label className="style-row" key={s.name}>
          <input type="checkbox" checked={chosen.has(s.name)} onChange={() => toggle(s.name)} />
          <span>
            <b>{s.name}</b>{" "}
            <span className="note">
              {lines(s.lines)} · {minutes(s.first)}–{minutes(s.last)}
            </span>
            <span className="samples">{s.samples.join(" ／ ")}</span>
          </span>
        </label>
      ))}
      {hidden.length > 0 && (
        <div>
          <button type="button" className="ghost" onClick={() => setAll(true)}>
            {tr(
              `还有 ${hidden.length} 种样式，共 ${hiddenLines} 句`,
              `${many(hidden.length, "more style")}, ${lines(hiddenLines)} in all`,
            )}
          </button>
        </div>
      )}
      {chosen.size === 0 && (
        <div className="note warn">{tr("至少勾一种", "Tick at least one")}</div>
      )}
      {marked}
    </div>
  );
}

export interface AddEpisodeProps {
  state: Summary;
  adding: Adding | null;
  setAdding: (adding: Adding) => void;
  onOpen: (episode: string) => void;
  toast: Toast;
}

/* The form for one episode, and the progress of the `avoc add` the server runs for it. `adding` is the server's job
   status, polled by App. */
export function AddEpisode({ state, adding, setAdding, onOpen, toast }: AddEpisodeProps) {
  const last = [...state.episodes].reverse().find((e) => e.offset != null);
  const [video, setVideo] = useState("");
  const [subtitles, setSubtitles] = useState("");
  const [textSubtitles, setTextSubtitles] = useState("");
  const [offset, setOffset] = useState(last ? String(last.offset) : "");
  const [busy, setBusy] = useState(false);
  /* The server's answer, and the text of the box it answers. */
  const [answer, setAnswer] = useState<{ for: string; found: Found } | null>(null);
  /* "Reading" is worked out here rather than set when the text changes: setting a new {} on every key made
     React stop with "Maximum update depth exceeded" when text arrived fast. */
  const found: Found = !subtitles.trim() ? null : answer?.for === subtitles ? answer.found : {};
  const [chosen, setChosen] = useState(new Set<string>());
  const log = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [adding?.lines.length]);
  /* Read the subtitles shortly after the path stops changing. An answer for an older path is dropped. */
  useEffect(() => {
    const path = subtitles.trim();
    if (!path) return;
    let current = true;
    const timer = setTimeout(
      () =>
        call<Styles>("/api/subtitle-styles", { path })
          .then((f) => {
            if (current) {
              setAnswer({ for: subtitles, found: f });
              setChosen(new Set(f.picked));
            }
          })
          .catch((e: Error) => {
            if (current) setAnswer({ for: subtitles, found: { error: e.message } });
          }),
      300,
    );
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [subtitles]);
  const run = async (body: object) => {
    setBusy(true);
    try {
      setAdding(await call<Adding>("/api/add", body));
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy(false);
  };
  const start = (e: FormEvent) => {
    e.preventDefault();
    const seconds = offset.trim() === "" ? null : Number(offset);
    if (seconds !== null && !Number.isFinite(seconds)) {
      toast(
        tr("字幕偏移要填一个数，比如 -0.95", "The subtitle offset must be a number, such as -0.95"),
        true,
      );
      return;
    }
    /* While the subtitles are still being read, or could not be read, the server picks the styles itself. */
    const styles = found?.styles
      ? found.styles.map((s) => s.name).filter((n) => chosen.has(n))
      : null;
    run({ video, subtitles, text_subtitles: textSubtitles, offset: seconds, styles });
  };
  const stop = async () => {
    setBusy(true);
    try {
      setAdding(await call<Adding>("/api/add/stop", {}));
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy(false);
  };
  const running = adding?.state === "running";
  const unfinished = Object.entries(state.skipped || {});
  const heading =
    adding &&
    {
      idle: "",
      running: tr(`正在加 ${adding.episode}…`, `Adding ${adding.episode}…`),
      done: tr(`${adding.episode} 加好了`, `${adding.episode} is added`),
      failed: tr(`${adding.episode} 没加成`, `${adding.episode} failed`),
      stopped: tr(`${adding.episode} 已停下`, `${adding.episode} was stopped`),
    }[adding.state];
  return (
    <div className="add-episode">
      {adding && adding.state !== "idle" && (
        <div className={`add-run ${adding.state}`}>
          <div className="add-head">
            <b>{heading}</b>
            <span className="note">{minutes(adding.seconds)}</span>
            <span className="spacer"></span>
            {running && (
              <button disabled={busy} onClick={stop}>
                {tr("停下", "Stop")}
              </button>
            )}
            {adding.state === "done" &&
              adding.episode &&
              state.episodes.some((e) => e.name === adding.episode) && (
                <button className="primary" onClick={() => onOpen(adding.episode as string)}>
                  {tr(`打开 ${adding.episode}`, `Open ${adding.episode}`)}
                </button>
              )}
          </div>
          <pre className="add-log" ref={log}>
            {adding.lines.join("\n") || tr("正在启动…", "Starting…")}
          </pre>
          {running && adding.bar && <div className="note add-bar">{adding.bar}</div>}
          {adding.state === "failed" && adding.errors?.length > 0 && (
            <pre className="add-log errors">{adding.errors.slice(-15).join("\n")}</pre>
          )}
          {running && (
            <div className="note">
              {tr(
                "有显卡时一集要几分钟，只用 CPU 会慢很多。可以关掉这个窗口接着标别的集，做完会提示。",
                "With a GPU one episode takes a few minutes; on the CPU it takes much longer. You can close this and keep labeling other episodes; you will be told when it is done.",
              )}
            </div>
          )}
          {(adding.state === "failed" || adding.state === "stopped") && (
            <div className="note">
              {tr(
                "改好问题以后再点「开始」。做完的步骤会留着，从停下的地方接着做。",
                "Fix the problem, then press Start again. Finished steps are kept, and it carries on from where it stopped.",
              )}
            </div>
          )}
        </div>
      )}
      {unfinished.length > 0 && (
        <div className="field">
          <label className="title">{tr("没做完的集", "Unfinished episodes")}</label>
          {unfinished.map(([name, why]) => (
            <div className="unfinished" key={name}>
              <b>{name}</b>
              <span className="note">{why}</span>
              <button disabled={busy || running} onClick={() => run({ resume: name })}>
                {tr("接着做", "Carry on")}
              </button>
            </div>
          ))}
        </div>
      )}
      <form className="add-form" onSubmit={start}>
        <div className="field">
          <label className="title">{tr("视频文件", "Video file")}</label>
          <input
            value={video}
            onChange={(e) => setVideo(e.target.value)}
            placeholder="D:\anime\Episode 01.mkv"
          />
        </div>
        <div className="field">
          <label className="title">
            {tr(
              "对白字幕（ASS 或 SRT，按它切台词）",
              "Dialogue subtitles (ASS or SRT; lines are cut from it)",
            )}
          </label>
          <input
            value={subtitles}
            onChange={(e) => setSubtitles(e.target.value)}
            placeholder="D:\anime\Episode 01.ass"
          />
          {found && (
            <SubtitleStyles key={subtitles} found={found} chosen={chosen} setChosen={setChosen} />
          )}
        </div>
        <div className="field">
          <label className="title">
            {tr(
              "台词文字字幕（可以不填。对白字幕是译文时，配一份原声语言的字幕，导出的文字从它取）",
              "Text subtitles (optional. If the dialogue subtitles are a translation, add subtitles in the language spoken; exported text is taken from them)",
            )}
          </label>
          <input
            value={textSubtitles}
            onChange={(e) => setTextSubtitles(e.target.value)}
            placeholder="D:\anime\Episode 01.ja.srt"
          />
        </div>
        <div className="field">
          <label className="title">{tr("字幕偏移（秒）", "Subtitle offset (seconds)")}</label>
          <input
            className="offset"
            value={offset}
            onChange={(e) => setOffset(e.target.value)}
            placeholder={tr("自动测", "measure")}
          />
          <div className="note">
            {tr(
              "字幕时间要加几秒才和声音对上。同一片源、同一字幕组的每一集都一样，所以默认填上一集的值。不知道就填 0，或者空着让它自动测（要 Hugging Face 令牌）。",
              "How many seconds to add to the subtitle times so they line up with the sound. It is the same for every episode from the same source and subtitle group, so the last episode's value is filled in. If you don't know, try 0, or leave it empty to measure it (needs a Hugging Face token).",
            )}
          </div>
        </div>
        <div className="note">
          {tr(
            "路径整段粘贴进来就行。Windows 上按住 Shift 右键文件，选「复制文件地址」。",
            'Paste the full paths. On Windows, hold Shift, right-click the file, and choose "Copy as path".',
          )}
        </div>
        <div>
          <button
            className="primary"
            type="submit"
            disabled={
              busy ||
              running ||
              !video.trim() ||
              !subtitles.trim() ||
              (!!found?.styles && chosen.size === 0)
            }
          >
            {tr("开始", "Start")}
          </button>
        </div>
      </form>
    </div>
  );
}

export function AddDialog({ onClose, ...props }: AddEpisodeProps & { onClose: () => void }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="help add-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{tr("加一集", "Add an episode")}</h2>
        <AddEpisode {...props} />
      </div>
    </div>
  );
}
