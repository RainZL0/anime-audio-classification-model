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
import { needsText } from "../purpose";
import type { Toast } from "../toast";

/* ───────────── Export ───────────── */

/* For each episode: the language spoken, and whether its main subtitles give the text in that language. */
function SpokenTexts({
  state,
  setState,
  toast,
}: {
  state: Summary;
  setState: (s: Summary) => void;
  toast: Toast;
}) {
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
        const s = e.spoken;
        return (
          <div
            className="grid grid-cols-[40px_auto_minmax(0,1fr)] items-center gap-2 text-[13px]"
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
            <span className="min-w-0">
              {s.source === "cut" ? (
                <span className="text-muted-foreground tabular-nums">
                  {tr("文字取自主字幕", "text from the main subtitles")}
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
            </span>
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
}: {
  state: Summary;
  setState: (s: Summary) => void;
  toast: Toast;
}) {
  const trainable = state.roles.filter((r) => r.confirmed > 0);
  /* The target characters start ticked: they are who the person is collecting. */
  const [ticked, setPicked] = useState(
    () => new Set(trainable.filter((r) => r.target).map((r) => r.name)),
  );
  /* Only names still on the list: a character ticked here may have been renamed or merged since. */
  const picked = new Set(trainable.map((r) => r.name).filter((n) => ticked.has(n)));
  /* What the voices are for was chosen at the start and is only shown here. Voices collected with their text can
     still be exported as sound only; voices collected as sound only have no text to export. */
  const soundOnly = !needsText();
  const [form, setForm] = useState<Form>(soundOnly ? "folder" : "gpt-sovits");
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
    ["folder", tr("只要声音（RVC 等）", "Sound only (RVC and such)")],
    ["gpt-sovits", tr("带文字（GPT-SoVITS）", "With text (GPT-SoVITS)")],
  ];
  return (
    <div className="mx-auto flex max-w-[860px] flex-col gap-6 pt-3 pb-10">
      <div className="flex flex-col gap-1 pt-3">
        <h2 className="text-lg font-semibold">{tr("导出训练数据", "Export training data")}</h2>
        <span className="text-[13px] text-muted-foreground">
          {tr(
            "每个角色一个文件夹：只有人声，音质和原片一样，音量统一",
            "One folder per character: voice only, the same quality as the video, even loudness",
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
        {soundOnly ? (
          <>
            <div className="text-sm font-medium">{forms[0][1]}</div>
            <Note>
              {tr(
                "开始时选的用途是「只要声音」，没有收集台词文字，所以只能这样导出。中途换用途还不支持。",
                'The purpose chosen at the start is "Sound only", so no text was collected and this is the only format. Switching midway is not supported yet.',
              )}
            </Note>
          </>
        ) : (
          <>
            <Choice value={form} options={forms} onPick={setForm} />
            <Note>
              {form === "folder"
                ? tr(
                    "只导出声音，不带文字，给 RVC 之类用。开始时选的用途「朗读文字」不变。",
                    'Sound only, no text, for RVC and such. The purpose chosen at the start, "Read text aloud", stays as it is.',
                  )
                : tr(
                    "连同每句台词的原声语言文本一起导出。没有文本的台词导不出来，标注时已经标出。",
                    "Exports each line with its text in the original language. Lines without that text cannot be exported; they are marked while labeling.",
                  )}
            </Note>
          </>
        )}
      </Section>
      {form !== "folder" && (
        <Section title={tr("台词文字", "Text of each line")}>
          <Note>
            {tr(
              "每句要配上角色说出口的原话，也就是这一集说的语言（一般是日语）。文字取自切台词用的主字幕，所以主字幕得是这种语言；用译文切的集只能导出声音。找不到原话的台词不导出，原因写在导出目录的 rejected.tsv 里。",
              "Each line needs the words the character actually said, in the language the episode speaks (usually Japanese). It comes from the main subtitles the lines were cut from, so they must be in that language; an episode cut from a translation can only be exported as sound. Lines without their words are not exported; the reasons are in rejected.tsv in the export folder.",
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
          <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {result.out}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                call("/api/show-folder", { path: result.out }).catch((e: Error) =>
                  toast(e.message, true),
                )
              }
            >
              {tr("打开文件夹", "Open the folder")}
            </Button>
          </span>
        </div>
      )}
    </div>
  );
}
