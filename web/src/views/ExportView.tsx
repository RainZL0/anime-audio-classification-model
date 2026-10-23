import { useEffect, useRef, useState } from "react";
import { call, type ExportResult, type Summary } from "../api";
import { Avatar } from "../components/Avatar";
import { PathInput } from "../components/PathInput";
import { RoleName } from "../components/RoleName";
import { pct } from "../format";
import { languageName, lines, many, SPOKEN, tr } from "../language";
import type { Toast } from "../toast";

/* ───────────── Export ───────────── */

/* For each episode: the language spoken and where the text in that language comes from. Text subtitles can be
   attached here; the server measures the offset and refuses ones that don't fit or are in another language. */
function SpokenTexts({
  state,
  setState,
  toast,
}: {
  state: Summary;
  setState: (s: Summary) => void;
  toast: Toast;
}) {
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const send = async (episode: string, url: string, body: object, done: string) => {
    setBusy(episode);
    try {
      setState(await call<Summary>(url, body));
      toast(done);
      return true;
    } catch (e) {
      toast((e as Error).message, true);
      return false;
    } finally {
      setBusy(null);
    }
  };
  const attach = async (episode: string) => {
    const ok = await send(
      episode,
      "/api/text-subtitles",
      { episode, path: paths[episode] || "" },
      tr(`${episode} 的台词字幕配好了`, `Text subtitles attached to ${episode}`),
    );
    if (ok) setPaths((p) => ({ ...p, [episode]: "" }));
  };
  const speak = (episode: string, language: string) =>
    send(
      episode,
      "/api/spoken-language",
      { episode, language },
      tr(
        `${episode} 改成说${languageName(language)}`,
        `${episode} now speaks ${languageName(language)}`,
      ),
    );
  return (
    <div className="text-subs">
      {state.episodes.map((e) => {
        const t = e.text_subtitles;
        const s = e.spoken;
        return (
          <div className="text-sub" key={e.name}>
            <span className="ep">{e.name}</span>
            <select
              value={s.language}
              disabled={busy !== null}
              onChange={(event) => speak(e.name, event.target.value)}
              title={
                s.assumed
                  ? tr(
                      "视频音轨没标语言，按日语算。不对就改",
                      "The audio track has no language tag, so Japanese is taken. Change it if wrong",
                    )
                  : tr("这一集说的语言", "The language spoken in this episode")
              }
            >
              {SPOKEN.map((code) => (
                <option key={code} value={code}>
                  {languageName(code)}
                  {code === s.language && s.assumed ? tr("（猜的）", " (assumed)") : ""}
                </option>
              ))}
            </select>
            <span className="now">
              {s.source === "text" && t ? (
                <>
                  <span className="file" title={t.file}>
                    {t.file}
                  </span>
                  <span className="min">
                    {tr(
                      `偏移 ${t.offset} 秒，重合 ${pct(t.agreement ?? 0)}`,
                      `offset ${t.offset} s, ${pct(t.agreement ?? 0)} overlap`,
                    )}
                  </span>
                </>
              ) : s.source === "cut" ? (
                <span className="min">{tr("切片段用的字幕就是", "the cutting subtitles are")}</span>
              ) : (
                <span className="note warn">{s.problem}</span>
              )}
              {s.blocked > 0 && s.source && (
                <span className="min">
                  {" · "}
                  {tr(`${s.blocked} 句对不上台词`, `${lines(s.blocked)} without matching text`)}
                </span>
              )}
              {t?.marked && <div className="note warn">{t.marked}</div>}
            </span>
            <PathInput
              kind="subtitles"
              placeholder={
                t
                  ? tr("换一份：字幕文件的路径", "Replace: path to a subtitle file")
                  : tr(
                      `${languageName(s.language)}字幕的路径（ASS 或 SRT）`,
                      `Path to ${languageName(s.language)} subtitles (ASS or SRT)`,
                    )
              }
              value={paths[e.name] || ""}
              onChange={(path) => setPaths((p) => ({ ...p, [e.name]: path }))}
              toast={toast}
            />
            <button
              disabled={busy !== null || !(paths[e.name] || "").trim()}
              onClick={() => attach(e.name)}
            >
              {busy === e.name ? tr("正在对…", "Aligning…") : tr("对齐并配上", "Align and attach")}
            </button>
          </div>
        );
      })}
    </div>
  );
}
type Form = "gpt-sovits" | "style-bert-vits2" | "folder";

export function ExportView({
  state,
  setState,
  toast,
}: {
  state: Summary;
  setState: (s: Summary) => void;
  toast: Toast;
}) {
  const trainable = state.roles.filter((r) => r.confirmed > 0);
  const [ticked, setPicked] = useState(() => new Set<string>());
  /* Only names still on the list: a character ticked here may have been renamed or merged since. */
  const picked = new Set(trainable.map((r) => r.name).filter((n) => ticked.has(n)));
  const [form, setForm] = useState<Form>("gpt-sovits");
  const [includeAuto, setIncludeAuto] = useState(false);
  /* Local date: toISOString gives UTC, which is still the day before in UTC+8 until 8 in the morning. */
  const [out, setOut] = useState(() => {
    const d = new Date();
    const two = (n: number) => String(n).padStart(2, "0");
    return `exports/${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);
  /* The result appears below the button, often off screen; bring it into view. */
  const resultBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (result) resultBox.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [result]);
  const toggle = (name: string) => {
    const next = new Set(picked);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setPicked(next);
  };
  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      setResult(
        await call<ExportResult>("/api/export", {
          roles: [...picked],
          include_auto: includeAuto,
          form,
          out,
        }),
      );
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy(false);
  };
  const forms: [Form, string][] = [
    ["gpt-sovits", "GPT-SoVITS"],
    ["style-bert-vits2", "Style-Bert-VITS2"],
    ["folder", tr("只要音频（RVC）", "Audio only (RVC)")],
  ];
  return (
    <div className="form">
      <div className="toolbar" style={{ paddingLeft: 0 }}>
        <h2>{tr("导出训练数据", "Export training data")}</h2>
        <span className="sub">
          {tr(
            "从原采样率的人声轨上切，统一响度，一个角色一个文件夹",
            "Cut from the vocals at the original sample rate, loudness evened out, one folder per character",
          )}
        </span>
      </div>
      <div className="field">
        <label className="title">{tr("导出哪些角色", "Characters to export")}</label>
        <div className="role-checks">
          {trainable.map((r) => (
            <label key={r.name} className={`check ${picked.has(r.name) ? "on" : ""}`}>
              <input type="checkbox" checked={picked.has(r.name)} onChange={() => toggle(r.name)} />
              <Avatar role={r} name={r.name} size="md" />
              <RoleName role={r} name={r.name} />
              <span className="min">
                {lines(r.confirmed)}
                {includeAuto && r.predicted ? ` + ${r.predicted}` : ""}
              </span>
            </label>
          ))}
        </div>
      </div>
      <div className="field">
        <label className="title">{tr("包括哪些台词", "Lines to include")}</label>
        <span className="seg">
          <button className={!includeAuto ? "on" : ""} onClick={() => setIncludeAuto(false)}>
            {tr("只要人确认过的", "Only confirmed by you")}
          </button>
          <button className={includeAuto ? "on" : ""} onClick={() => setIncludeAuto(true)}>
            {tr("再加上机器有把握的", "Plus the machine's confident ones")}
          </button>
        </span>
        <div className="note" style={{ marginTop: "6px" }}>
          {includeAuto
            ? tr(
                `机器有把握指把握不低于 ${pct(state.model.auto_confidence)}，第 3 集上这一档约 97% 判对。训练数据里混进别人的声音，模型就会学歪。`,
                `Confident means at least ${pct(state.model.auto_confidence)} sure; on episode 3 about 97% of these were right. Other people's voices in the training data make the voice model learn the wrong thing.`,
              )
            : tr(
                "最干净。数据不够时再考虑加上机器有把握的。",
                "The cleanest. Add the machine's confident ones only if you don't have enough.",
              )}
        </div>
      </div>
      <div className="field">
        <label className="title">{tr("格式", "Format")}</label>
        <span className="seg">
          {forms.map(([v, l]) => (
            <button key={v} className={form === v ? "on" : ""} onClick={() => setForm(v)}>
              {l}
            </button>
          ))}
        </span>
      </div>
      {form !== "folder" && (
        <div className="field">
          <label className="title">{tr("台词文字", "Text of each line")}</label>
          <div className="note">
            {tr(
              "训练要的是真正说出口的话，所以文字用每集说的语言：切片段用的字幕就是这种语言时直接用，不是的话（比如中文译文）就用下面另配的字幕。没有这种文字的片段不导出，原因写进导出目录的 rejected.tsv。",
              "Training needs the words actually said, so the text is in the language each episode speaks: taken from the cutting subtitles when they are in that language, and otherwise (a translation, say) from the subtitles attached below. Clips without such text are not exported; the reasons go into rejected.tsv in the export folder.",
            )}
          </div>
          <SpokenTexts state={state} setState={setState} toast={toast} />
        </div>
      )}
      <div className="field">
        <label className="title">
          {tr(
            "输出到（相对路径从启动目录算起）",
            "Output folder (relative paths start from where you launched avoc)",
          )}
        </label>
        <PathInput kind="folder" value={out} onChange={setOut} toast={toast} />
      </div>
      <div>
        <button className="primary" disabled={busy || picked.size === 0} onClick={run}>
          {busy
            ? tr("正在导出…", "Exporting…")
            : tr(`导出 ${picked.size} 个角色`, `Export ${many(picked.size, "character")}`)}
        </button>
      </div>
      {result && (
        <div className="result" ref={resultBox}>
          <b>{tr("导出好了：", "Exported: ")}</b>
          {tr(
            `${result.files} 个文件，共 ${Math.round(result.total_sec / 6) / 10} 分钟`,
            `${many(result.files, "file")}, ${Math.round(result.total_sec / 6) / 10} minutes in total`,
          )}
          <br />
          {Object.keys(result.rejected || {}).length > 0 && (
            <span>
              {tr("没导出：", "Not exported: ")}
              {Object.entries(result.rejected)
                .map(([why, n]) => tr(`${why} ${n} 条`, `${why} (${n})`))
                .join(tr("，", ", "))}
              {tr("。明细见 rejected.tsv", ". Details in rejected.tsv")}
              <br />
            </span>
          )}
          <span className="note">{result.out}</span>
        </div>
      )}
    </div>
  );
}
