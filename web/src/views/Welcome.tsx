import { currentLanguage, tr } from "../language";
import { AddEpisode, Checks, type AddEpisodeProps } from "./AddEpisode";

/* ───────────── The first-use guide ───────────── */

/* The page for a workspace with no usable episode yet: what the tool does, the machine checks, and the form. */
export function Welcome(props: AddEpisodeProps) {
  return (
    <div className="mx-auto flex max-w-[720px] flex-col gap-8 pt-6 pb-15">
      <div>
        <h2 className="mb-1.5 text-xl font-semibold">{tr("欢迎", "Welcome")}</h2>
        <p className="text-muted-foreground">
          {tr(
            "这个工具把一个动画角色说的每一句台词收集成干净的单人音频，带上台词文字，可以直接拿去训练语音模型。",
            "This tool collects every line one anime character speaks as clean single-speaker audio with its text, ready for training a voice model.",
          )}
        </p>
        {/* How to label is told once, in the getting-started guide, which opens by itself after this. */}
        <p className="mt-1.5 text-muted-foreground">
          {tr(
            "先加一集：给出视频和对白字幕。加好以后，顶栏的「指南」讲怎么一步步标到导出，第一次会自己打开。",
            "First add an episode: give its video and dialogue subtitles. Once it is in, Guide in the top bar shows how to go from labeling to export; it opens by itself the first time.",
          )}
        </p>
      </div>
      <section className="flex flex-col gap-3">
        <h3 className="text-base font-semibold">{tr("这台机器", "This machine")}</h3>
        <Checks key={currentLanguage()} />
      </section>
      <section className="flex flex-col gap-3">
        <h3 className="text-base font-semibold">{tr("加第一集", "Add the first episode")}</h3>
        <AddEpisode {...props} />
      </section>
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
