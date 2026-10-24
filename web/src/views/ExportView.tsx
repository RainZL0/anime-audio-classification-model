import { useEffect, useRef, useState } from "react";
import { call, type ExportResult, type Summary } from "../api";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Avatar } from "../components/Avatar";
import { Note } from "../components/Notes";
import { Choice } from "../components/Choice";
import { PathInput } from "../components/PathInput";
import { RoleName } from "../components/RoleName";
import { Section } from "../components/Section";
import { Tip } from "../components/Tip";
import { pct } from "../format";
import { languageName, lines, many, SPOKEN, tr } from "../language";
import { needsText, type Purpose } from "../purpose";
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
    <div className="mt-2 flex flex-col gap-1.5">
      {state.episodes.map((e) => {
        const t = e.text_subtitles;
        const s = e.spoken;
        return (
          <div
            /* When the page is narrow, the path box and its button go to a second line, so the text in the middle
               is not squeezed into a thin column. */
            className="grid grid-cols-[40px_auto_minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 text-[13px] @max-5xl:grid-cols-[40px_auto_minmax(0,1fr)_auto]"
            key={e.name}
          >
            <span className="text-muted-foreground tabular-nums">{e.name}</span>
            <Tip
              text={
                s.assumed
                  ? tr(
                      "视频音轨没标语言，按日语算。不对就改",
                      "The audio track has no language tag, so Japanese is taken. Change it if wrong",
                    )
                  : tr("这一集说的语言", "The language spoken in this episode")
              }
            >
              <NativeSelect
                value={s.language}
                disabled={busy !== null}
                onChange={(event) => speak(e.name, event.target.value)}
              >
                {SPOKEN.map((code) => (
                  <NativeSelectOption key={code} value={code}>
                    {languageName(code)}
                    {code === s.language && s.assumed ? tr("（猜的）", " (assumed)") : ""}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Tip>
            <span className="min-w-0 @max-5xl:col-span-2">
              {s.source === "text" && t ? (
                <>
                  <Tip text={t.file}>
                    <span className="block truncate">{t.file}</span>
                  </Tip>
                  <span className="text-muted-foreground tabular-nums">
                    {tr(
                      `偏移 ${t.offset} 秒，重合 ${pct(t.agreement ?? 0)}`,
                      `offset ${t.offset} s, ${pct(t.agreement ?? 0)} overlap`,
                    )}
                  </span>
                </>
              ) : s.source === "cut" ? (
                <span className="text-muted-foreground tabular-nums">
                  {tr("文字取自切片段用的字幕", "text from the subtitles the clips were cut from")}
                </span>
              ) : (
                <span className="text-warning">{s.problem}</span>
              )}
              {s.blocked > 0 && s.source && (
                <span className="text-muted-foreground tabular-nums">
                  {" · "}
                  {tr(`${s.blocked} 句对不上台词`, `${lines(s.blocked)} without matching text`)}
                </span>
              )}
              {t?.marked && <Note warn>{t.marked}</Note>}
            </span>
            {/* Cut from subtitles in the spoken language, each clip already has its own line: nothing to attach. */}
            {s.source !== "cut" && (
              <>
                <PathInput
                  className="@max-5xl:col-span-2 @max-5xl:col-start-2"
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
                <Button
                  variant="outline"
                  disabled={busy !== null || !(paths[e.name] || "").trim()}
                  onClick={() => attach(e.name)}
                >
                  {busy === e.name
                    ? tr("正在对…", "Aligning…")
                    : tr("对齐并配上", "Align and attach")}
                </Button>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
type Form = "gpt-sovits" | "folder";

export function ExportView({
  state,
  setState,
  toast,
  onPurpose,
}: {
  state: Summary;
  setState: (s: Summary) => void;
  toast: Toast;
  onPurpose: (purpose: Purpose) => void;
}) {
  const trainable = state.roles.filter((r) => r.confirmed > 0);
  const [ticked, setPicked] = useState(() => new Set<string>());
  /* Only names still on the list: a character ticked here may have been renamed or merged since. */
  const picked = new Set(trainable.map((r) => r.name).filter((n) => ticked.has(n)));
  const [form, setFormState] = useState<Form>(needsText() ? "gpt-sovits" : "folder");
  /* The format also says what the voices are for, so the labeling views show or leave out the text parts. */
  const setForm = (next: Form) => {
    setFormState(next);
    onPurpose(next === "folder" ? "audio" : "tts");
  };
  const [includeAuto, setIncludeAuto] = useState(false);
  const [out, setOut] = useState(state.export_folder);
  /* The default folder now in the box. After an export it moves on to the next free one, unless the person typed
     or picked their own. */
  const [suggested, setSuggested] = useState(state.export_folder);
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
      const done = await call<ExportResult>("/api/export", {
        roles: [...picked],
        include_auto: includeAuto,
        form,
        out,
      });
      setResult(done);
      if (out === suggested) {
        setOut(done.next);
        setSuggested(done.next);
      }
    } catch (e) {
      toast((e as Error).message, true);
    }
    setBusy(false);
  };
  const forms: [Form, string][] = [
    ["gpt-sovits", "GPT-SoVITS"],
    ["folder", tr("只要音频（RVC）", "Audio only (RVC)")],
  ];
  return (
    <div className="mx-auto flex max-w-[860px] flex-col gap-6 pt-3 pb-10">
      <div className="flex flex-col gap-1 pt-3">
        <h2 className="text-lg font-semibold">{tr("导出训练数据", "Export training data")}</h2>
        <span className="text-[13px] text-muted-foreground">
          {tr(
            "从原采样率的人声轨上切，统一响度，一个角色一个文件夹",
            "Cut from the vocals at the original sample rate, loudness evened out, one folder per character",
          )}
        </span>
      </div>
      <Section title={tr("导出哪些角色", "Characters to export")}>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-1.5">
          {trainable.map((r) => (
            <label
              key={r.name}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 transition-colors hover:border-primary/40",
                picked.has(r.name) && "border-primary/40 bg-accent",
              )}
            >
              <Checkbox checked={picked.has(r.name)} onCheckedChange={() => toggle(r.name)} />
              <Avatar role={r} name={r.name} size="md" />
              <RoleName role={r} name={r.name} />
              <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                {lines(r.confirmed)}
                {includeAuto && r.predicted ? ` + ${r.predicted}` : ""}
              </span>
            </label>
          ))}
        </div>
      </Section>
      <Section title={tr("包括哪些台词", "Lines to include")}>
        <Choice
          value={includeAuto ? "auto" : "confirmed"}
          options={[
            ["confirmed", tr("只要人确认过的", "Only confirmed by you")],
            ["auto", tr("再加上机器有把握的", "Plus the machine's confident ones")],
          ]}
          onPick={(v) => setIncludeAuto(v === "auto")}
        />
        <Note>
          {includeAuto
            ? tr(
                `机器有把握指把握不低于 ${pct(state.model.auto_confidence)}，第 3 集上这一档约 97% 判对。训练数据里混进别人的声音，模型就会学歪。`,
                `Confident means at least ${pct(state.model.auto_confidence)} sure; on episode 3 about 97% of these were right. Other people's voices in the training data make the voice model learn the wrong thing.`,
              )
            : tr(
                "最干净。数据不够时再考虑加上机器有把握的。",
                "The cleanest. Add the machine's confident ones only if you don't have enough.",
              )}
        </Note>
      </Section>
      <Section title={tr("格式", "Format")}>
        <Choice value={form} options={forms} onPick={setForm} />
        <Note>
          {form === "folder"
            ? tr(
                "只要声音，不用文字。标注时也不再显示「导不出文字」之类的提示。这个选择会记住。",
                'Sound only, no text. While labeling, notes such as "No text to export" are left out too. This choice is remembered.',
              )
            : tr(
                "连同每句台词的原声语言文本一起导出。标注时会标出没有文本、导不出来的句子。这个选择会记住。",
                "Exports each line with its text in the original language. While labeling, lines without that text, which cannot be exported, are marked. This choice is remembered.",
              )}
        </Note>
      </Section>
      {form !== "folder" && (
        <Section title={tr("台词文字", "Text of each line")}>
          <Note>
            {tr(
              "训练要的是真正说出口的话，所以文字用每集说的语言：切片段用的字幕就是这种语言时直接用，不是的话（比如中文译文）就用下面另配的字幕。没有这种文字的片段不导出，原因写进导出目录的 rejected.tsv。",
              "Training needs the words actually said, so the text is in the language each episode speaks: taken from the cutting subtitles when they are in that language, and otherwise (a translation, say) from the subtitles attached below. Clips without such text are not exported; the reasons go into rejected.tsv in the export folder.",
            )}
          </Note>
          <SpokenTexts state={state} setState={setState} toast={toast} />
        </Section>
      )}
      <Section title={tr("输出到", "Output folder")}>
        <PathInput kind="folder" value={out} onChange={setOut} toast={toast} />
        <Note>
          {tr(
            "相对路径从启动 avoc 的目录算起。",
            "A relative path starts from the folder you launched avoc in.",
          )}
        </Note>
      </Section>
      <div>
        <Button disabled={busy || picked.size === 0} onClick={run}>
          {busy
            ? tr("正在导出…", "Exporting…")
            : tr(`导出 ${picked.size} 个角色`, `Export ${many(picked.size, "character")}`)}
        </Button>
      </div>
      {result && (
        <div className="rounded-xl bg-success/10 px-3.5 py-3" ref={resultBox}>
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
          <span className="text-xs text-muted-foreground">{result.out}</span>
        </div>
      )}
    </div>
  );
}
