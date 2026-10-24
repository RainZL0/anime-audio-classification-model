import { tr } from "../language";
import { AddEpisode, type AddEpisodeProps } from "./AddEpisode";

/* ───────────── An empty workspace ───────────── */

/* With no episode yet, the page is the same "Add an episode" form as the dialog, with one line on what the tool
   is for. How to label is told in the getting-started guide, which opens by itself once the episode is in. */
export function Welcome(props: AddEpisodeProps) {
  return (
    <div className="mx-auto flex max-w-[720px] flex-col gap-6 pt-6 pb-15">
      <div>
        <h2 className="mb-1.5 text-xl font-semibold">{tr("加第一集", "Add the first episode")}</h2>
        <p className="text-muted-foreground">
          {tr(
            "这个工具把一个动画角色说的每一句台词收集成干净的单人音频，带上台词文字，可以直接拿去训练语音模型。",
            "This tool collects every line one anime character speaks as clean single-speaker audio with its text, ready for training a voice model.",
          )}
        </p>
      </div>
      <AddEpisode {...props} />
    </div>
  );
}
