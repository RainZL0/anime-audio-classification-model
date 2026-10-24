import { Field, FieldLabel } from "@/components/ui/field";
import { currentLanguage, tr } from "../language";
import { AddEpisode, Checks, type AddEpisodeProps } from "./AddEpisode";

/* ───────────── The first-use guide ───────────── */

/* The page for a workspace with no usable episode yet: what the tool does, the machine checks, and the form. */
export function Welcome(props: AddEpisodeProps) {
  return (
    <div className="mx-auto flex max-w-[720px] flex-col gap-[18px] pt-6 pb-15">
      <div>
        <h2 className="mb-1.5 text-xl font-semibold">{tr("欢迎", "Welcome")}</h2>
        <p className="text-muted-foreground">
          {tr(
            "这个工具把一个动画角色说的每一句台词收集成干净的单人音频，带上台词文字，可以直接拿去训练语音模型。",
            "This tool collects every line one anime character speaks as clean single-speaker audio with its text, ready for training a voice model.",
          )}
        </p>
        <ol className="mt-2.5 flex list-decimal flex-col gap-1 pl-5 text-muted-foreground">
          <li>
            {tr(
              "加一集：给出视频和对白字幕。机器按字幕切台词，再把人声和音乐分开。",
              "Add an episode: give its video and dialogue subtitles. The machine cuts the lines along the subtitles and separates the voices from the music.",
            )}
          </li>
          <li>
            {tr(
              "在「起步分组」里给你要的角色起名，其他人都标「其他」。",
              'In Groups, name the character you want, and label everyone else "Other".',
            )}
          </li>
          <li>
            {tr(
              "在「场景」和「角色」里改机器猜错的。每改一次，机器马上重学。",
              "In Scenes and Characters, fix the machine's wrong guesses. It retrains after every fix.",
            )}
          </li>
          <li>
            {tr(
              "在「导出」里导出成 GPT-SoVITS、Style-Bert-VITS2 或 RVC 用的格式。",
              "In Export, export for GPT-SoVITS, Style-Bert-VITS2 or RVC.",
            )}
          </li>
        </ol>
      </div>
      <Field className="gap-1.5">
        <FieldLabel className="text-xs font-normal text-muted-foreground">
          {tr("这台机器", "This machine")}
        </FieldLabel>
        <Checks key={currentLanguage()} />
      </Field>
      <Field className="gap-1.5">
        <FieldLabel className="text-xs font-normal text-muted-foreground">
          {tr("加第一集", "Add the first episode")}
        </FieldLabel>
        <AddEpisode {...props} />
      </Field>
      <p className="text-xs text-muted-foreground">
        {tr(
          <>
            也可以在命令行里加：
            <code className="font-mono">
              uv run avoc add "{props.state.workspace}" 视频 --subs 字幕
            </code>
          </>,
          <>
            You can also add one in a terminal:{" "}
            <code className="font-mono">
              uv run avoc add "{props.state.workspace}" VIDEO --subs SUBTITLES
            </code>
          </>,
        )}
      </p>
    </div>
  );
}
