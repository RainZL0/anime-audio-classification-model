import { useEffect, useRef, useState } from "react";
import { call, type ExportResult, type Summary } from "../api";
import { Avatar } from "../components/Avatar";
import { PathInput } from "../components/PathInput";
import { RoleName } from "../components/RoleName";
import { pct } from "../format";
import { lines, many, tr } from "../language";
import type { Toast } from "../toast";

/* ───────────── Export ───────────── */

/* Text subtitles for each episode: paste a path; the server measures the offset and refuses ones that don't fit. */
function TextSubtitles({
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
  const attach = async (episode: string) => {
    setBusy(episode);
    try {
      setState(await call<Summary>("/api/text-subtitles", { episode, path: paths[episode] || "" }));
      setPaths({ ...paths, [episode]: "" });
      toast(tr(`${episode} 的台词字幕配好了`, `Text subtitles attached to ${episode}`));
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy(null);
  };
  return (
    <div className="text-subs">
      {state.episodes.map((e) => {
        const t = e.text_subtitles;
        return (
          <div className="text-sub" key={e.name}>
            <span className="ep">{e.name}</span>
            <span className="now">
              {t ? (
                <>
                  {t.file}{" "}
                  <span className="min">
                    {tr(
                      `偏移 ${t.offset} 秒，重合 ${pct(t.agreement ?? 0)}`,
                      `offset ${t.offset} s, ${pct(t.agreement ?? 0)} overlap`,
                    )}
                  </span>
                  {t.marked && <div className="note warn">{t.marked}</div>}
                </>
              ) : (
                <span className="min">{tr("还没配", "none yet")}</span>
              )}
            </span>
            <PathInput
              kind="subtitles"
              placeholder={
                t
                  ? tr("换一份：字幕文件的路径", "Replace: path to a subtitle file")
                  : tr("字幕文件的路径（ASS 或 SRT）", "Path to a subtitle file (ASS or SRT)")
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
  const [language, setLanguage] = useState("ja");
  const [textSubtitles, setTextSubtitles] = useState(() =>
    state.episodes.some((e) => e.text_subtitles),
  );
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
          language,
          out,
          text_subtitles: textSubtitles,
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
  const languages: [string, string][] = [
    ["ja", tr("日语", "Japanese")],
    ["zh", tr("中文", "Chinese")],
    ["en", tr("英语", "English")],
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
          <label className="title">{tr("台词文字的语言", "Language of the text")}</label>
          <span className="seg">
            {languages.map(([v, l]) => (
              <button key={v} className={language === v ? "on" : ""} onClick={() => setLanguage(v)}>
                {l}
              </button>
            ))}
          </span>
        </div>
      )}
      {form !== "folder" && (
        <div className="field">
          <label className="title">{tr("台词文字从哪来", "Where the text comes from")}</label>
          <span className="seg">
            <button className={!textSubtitles ? "on" : ""} onClick={() => setTextSubtitles(false)}>
              {tr("切片段用的字幕", "The subtitles used to cut clips")}
            </button>
            <button className={textSubtitles ? "on" : ""} onClick={() => setTextSubtitles(true)}>
              {tr("每集另配的台词字幕", "Text subtitles for each episode")}
            </button>
          </span>
          {textSubtitles ? (
            <>
              <div className="note" style={{ marginTop: "6px" }}>
                {tr(
                  "片段不变，文字换成另配字幕里同一时间的台词。找不全台词、或者混着别人的话的片段不导出，原因写进导出目录的 rejected.tsv。",
                  "The clips stay the same; the text is taken from the lines at the same time in the text subtitles. Clips whose line can't be found in full, or that include someone else's words, are not exported; the reasons go into rejected.tsv in the export folder.",
                )}
              </div>
              <TextSubtitles state={state} setState={setState} toast={toast} />
            </>
          ) : (
            <div className="note warn" style={{ marginTop: "6px" }}>
              {tr(
                "切片段用的字幕是中文译文时，文字和日语声音对不上。训练日语模型请改用另配的日文字幕。",
                "If the subtitles used to cut clips are a translation, the text won't match the Japanese voices. For a Japanese voice model, use separate Japanese text subtitles.",
              )}
            </div>
          )}
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
