import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  call,
  type Adding,
  type AudioTracks,
  type Check,
  type Summary,
  type SubtitleStyles as Styles,
} from "../api";
import { PathInput } from "../components/PathInput";
import { minutes } from "../format";
import { languageName, languageNames, lines, many, SPOKEN, tr } from "../language";
import { needsText, type Purpose } from "../purpose";
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
  const said = languageNames(found.languages ?? []);
  const read = tr(`${format}，${found.encoding}，${said}`, `${format}, ${found.encoding}, ${said}`);
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

/* Ask the server about a path shortly after it stops changing. An answer for an older path is dropped. `null`
   while there is no path or no answer yet. */
type Answer<T> = Partial<T> & { error?: string };

function useAnswer<T>(url: string, path: string): Answer<T> | null {
  const [answer, setAnswer] = useState<{ for: string; found: Answer<T> } | null>(null);
  useEffect(() => {
    const clean = path.trim();
    if (!clean) return;
    let current = true;
    const timer = setTimeout(
      () =>
        call<T>(url, { path: clean })
          .then((found) => current && setAnswer({ for: path, found: found as Answer<T> }))
          .catch(
            (e: Error) =>
              current && setAnswer({ for: path, found: { error: e.message } as Answer<T> }),
          ),
      300,
    );
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [url, path]);
  return path.trim() && answer?.for === path ? answer.found : null;
}

/* Which audio track the voices are taken from, and the language it speaks. */
function TrackNote({ tracks, spoken }: { tracks: AudioTracks; spoken: string }) {
  if (!tracks.tracks.length)
    return <div className="note warn">{tr("视频里没有音轨", "The video has no audio track")}</div>;
  const tagged = tracks.tracks.find((t) => t.language === spoken);
  const used = tagged ?? tracks.tracks.find((t) => t.default) ?? tracks.tracks[0];
  const what = [
    used.language ? languageName(used.language) : used.tag || tr("没标语言", "no language tag"),
    used.title,
  ]
    .filter(Boolean)
    .join(tr("，", ", "));
  return (
    <div className={`note ${tagged || tracks.tracks.length === 1 ? "" : "warn"}`}>
      {tr(
        `共 ${tracks.tracks.length} 条音轨，人声从第 ${used.number + 1} 条（${what}）取`,
        `${many(tracks.tracks.length, "audio track")}; the voices are taken from track ${used.number + 1} (${what})`,
      )}
      {!tagged &&
        tracks.tracks.length > 1 &&
        tr(
          `。没有标成${languageName(spoken)}的音轨，确认一下`,
          `. No track is tagged ${languageName(spoken)}; check it`,
        )}
    </div>
  );
}

export interface AddEpisodeProps {
  state: Summary;
  adding: Adding | null;
  setAdding: (adding: Adding) => void;
  onOpen: (episode: string) => void;
  toast: Toast;
  onPurpose: (purpose: Purpose) => void;
}

/* The form for one episode, and the progress of the `avoc add` the server runs for it. `adding` is the server's job
   status, polled by App. */
export function AddEpisode({
  state,
  adding,
  setAdding,
  onOpen,
  toast,
  onPurpose,
}: AddEpisodeProps) {
  const text = needsText();
  const last = [...state.episodes].reverse().find((e) => e.offset != null);
  const [video, setVideo] = useState("");
  const [subtitles, setSubtitles] = useState("");
  const [textSubtitles, setTextSubtitles] = useState("");
  const [displaySubtitles, setDisplaySubtitles] = useState("");
  const [offset, setOffset] = useState(last ? String(last.offset) : "");
  /* "" lets the audio track's tag decide. */
  const [spoken, setSpoken] = useState("");
  const tracks = useAnswer<AudioTracks>("/api/audio-tracks", video);
  const textFound = useAnswer<Styles>("/api/subtitle-styles", textSubtitles);
  const heard = spoken || tracks?.language || "ja";
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
    run({
      video,
      subtitles,
      text_subtitles: text ? textSubtitles : "",
      display_subtitles: displaySubtitles,
      offset: seconds,
      styles,
      spoken: spoken || null,
    });
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
          <label className="title">{tr("收集声音做什么用", "What the voices are for")}</label>
          <span className="seg">
            <button type="button" className={text ? "on" : ""} onClick={() => onPurpose("tts")}>
              {tr("语音合成（GPT-SoVITS 等）", "Speech synthesis (GPT-SoVITS and such)")}
            </button>
            <button type="button" className={text ? "" : "on"} onClick={() => onPurpose("audio")}>
              {tr("只要声音（RVC 等）", "Sound only (RVC and such)")}
            </button>
          </span>
          <div className="note">
            {text
              ? tr(
                  "语音合成要每句说的话，用这一集说的语言（一般是日语），所以要有这种语言的字幕。",
                  "Speech synthesis needs the words of each line in the language spoken (usually Japanese), so subtitles in that language are needed.",
                )
              : tr(
                  "只要声音就不用管台词文字，什么语言的字幕都行。以后在导出页也能改。",
                  "Sound only needs no text, so subtitles in any language will do. You can change this later on the Export page.",
                )}
          </div>
        </div>
        <div className="field">
          <label className="title">{tr("视频文件", "Video file")}</label>
          <PathInput
            kind="video"
            value={video}
            onChange={setVideo}
            placeholder="D:\anime\Episode 01.mkv"
            toast={toast}
          />
          {tracks &&
            (tracks.error ? (
              <div className="note warn">{tracks.error}</div>
            ) : (
              tracks.tracks && <TrackNote tracks={tracks as AudioTracks} spoken={heard} />
            ))}
        </div>
        <div className="field">
          <label className="title">{tr("说的语言", "Language spoken")}</label>
          <select value={spoken} onChange={(e) => setSpoken(e.target.value)}>
            <option value="">
              {tracks?.language
                ? tr(
                    `按音轨标的：${languageName(tracks.language)}`,
                    `From the audio track: ${languageName(tracks.language)}`,
                  )
                : tr("按音轨标的（没标就算日语）", "From the audio track (Japanese if not tagged)")}
            </option>
            {SPOKEN.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </select>
          <div className="note">
            {text
              ? tr(
                  "人声从这种语言的音轨取，导出的文字也要是这种语言。双语视频里想要配音版的声音，就在这里选配音的语言。",
                  "The voices are taken from the audio track in this language, and exported text must be in it too. For the dub of a dual-audio video, pick the dub's language here.",
                )
              : tr(
                  "人声从这种语言的音轨取。双语视频里想要配音版的声音，就在这里选配音的语言。",
                  "The voices are taken from the audio track in this language. For the dub of a dual-audio video, pick the dub's language here.",
                )}
          </div>
        </div>
        <div className="field">
          <label className="title">
            {text
              ? tr(
                  "对白字幕（ASS 或 SRT，按它切台词。最好用说的语言的字幕）",
                  "Dialogue subtitles (ASS or SRT; lines are cut from it. Best in the language spoken)",
                )
              : tr(
                  "对白字幕（ASS 或 SRT，按它切台词）",
                  "Dialogue subtitles (ASS or SRT; lines are cut from it)",
                )}
          </label>
          <PathInput
            kind="subtitles"
            value={subtitles}
            onChange={setSubtitles}
            placeholder="D:\anime\Episode 01.ja.srt"
            toast={toast}
          />
          {found && (
            <SubtitleStyles key={subtitles} found={found} chosen={chosen} setChosen={setChosen} />
          )}
          {found?.languages?.length === 1 && found.languages[0] === heard && (
            <div className="note">
              {text
                ? tr(
                    "对白字幕就是说的语言：每段片段的文字就是它自己那一句。一条字幕里有两个人说话（用「－」或名字标出）的，按人分开切。",
                    "The dialogue subtitles are in the language spoken, so each clip's text is its own line. An entry where two people speak (marked with a dash or a name) is cut into one clip per person.",
                  )
                : tr(
                    "对白字幕就是说的语言：一条字幕里有两个人说话（用「－」或名字标出）的，按人分开切。",
                    "The dialogue subtitles are in the language spoken: an entry where two people speak (marked with a dash or a name) is cut into one clip per person.",
                  )}
            </div>
          )}
        </div>
        <div className="field">
          <label className="title">
            {tr(
              "显示用字幕（可以不填。对白字幕是你看不懂的语言时，配一份译文，标注时显示在台词上面；导出不用它）",
              "Display subtitles (optional. If you don't read the dialogue subtitles' language, add a translation; it is shown above each line while labeling, and never exported)",
            )}
          </label>
          <PathInput
            kind="subtitles"
            value={displaySubtitles}
            onChange={setDisplaySubtitles}
            placeholder="D:\anime\Episode 01.zh.ass"
            toast={toast}
          />
        </div>
        {text && (
          <div className="field">
            <label className="title">
              {tr(
                "台词文字字幕（可以不填。对白字幕是译文时，配一份原声语言的字幕，导出的文字从它取）",
                "Text subtitles (optional. If the dialogue subtitles are a translation, add subtitles in the language spoken; exported text is taken from them)",
              )}
            </label>
            <PathInput
              kind="subtitles"
              value={textSubtitles}
              onChange={setTextSubtitles}
              placeholder="D:\anime\Episode 01.ja.srt"
              toast={toast}
            />
            {textFound?.error && <div className="note warn">{textFound.error}</div>}
            {textFound?.languages && (
              <div className={`note ${textFound.languages.includes(heard) ? "" : "warn"}`}>
                {textFound.languages.includes(heard)
                  ? tr(
                      `${languageNames(textFound.languages)}，导出的文字取其中的${languageName(heard)}`,
                      `${languageNames(textFound.languages)}; the ${languageName(heard)} lines are exported`,
                    )
                  : tr(
                      `这份字幕是${languageNames(textFound.languages)}，不是${languageName(heard)}，会被拒绝`,
                      `These subtitles are in ${languageNames(textFound.languages)}, not ${languageName(heard)}, so they will be refused`,
                    )}
              </div>
            )}
            {!textSubtitles.trim() &&
              found?.languages &&
              found.languages.length > 0 &&
              !found.languages.includes(heard) && (
                <div className="note warn">
                  {tr(
                    `对白字幕是${languageNames(found.languages)}，这一集说${languageName(heard)}。导出 GPT-SoVITS 或 Style-Bert-VITS2 要有${languageName(heard)}台词：现在配上，或者以后在导出页配。只导出音频（RVC）不需要。有${languageName(heard)}字幕的话，更好的做法是把它当对白字幕，这份当显示用字幕：按译文切的片段和原文时间对不齐，不少句子会导不出文字。`,
                    `The dialogue subtitles are in ${languageNames(found.languages)}, but this episode speaks ${languageName(heard)}. Exporting for GPT-SoVITS or Style-Bert-VITS2 needs the ${languageName(heard)} text: attach it now, or later on the Export page. Audio-only export (RVC) does not need it. If you have ${languageName(heard)} subtitles, it is better to use them as the dialogue subtitles and these as the display subtitles: clips cut from a translation often don't line up with the original lines, and many cannot be exported with text.`,
                  )}
                </div>
              )}
          </div>
        )}
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
            "按「浏览…」选文件，或者把整段路径粘贴进框里。Windows 上按住 Shift 右键文件，选「复制文件地址」。",
            'Press "Browse…" to pick each file, or paste its full path into the box. On Windows, hold Shift, right-click the file, and choose "Copy as path".',
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
