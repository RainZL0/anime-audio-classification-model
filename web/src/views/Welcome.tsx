import { cn } from "cn";
import { currentLanguage, languageChosen, tr, type Language } from "../language";
import { AddEpisode, type AddEpisodeProps } from "./AddEpisode";

/* ───────────── An empty workspace ───────────── */

/* The language the page starts in follows the browser, which may not be the person's. Until they pick one, a
   light line at the top offers both, written in both, so it can be read whichever language is showing. */
function PickLanguage({ onPick }: { onPick: (next: Language) => void }) {
  const choice = (code: Language, name: string) => (
    <button
      type="button"
      className={cn(
        "underline-offset-2 hover:text-foreground hover:underline",
        currentLanguage() === code && "font-semibold text-foreground",
      )}
      onClick={() => onPick(code)}
    >
      {name}
    </button>
  );
  return (
    <div className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
      界面语言 / Language:
      {choice("zh", "中文")}
      <span>·</span>
      {choice("en", "English")}
    </div>
  );
}

/* With no episode yet, the page is the same "Add an episode" form as the dialog, with one line on what the tool
   is for and every machine check ticked off. How to label is told in the getting-started guide, which opens by itself once the episode is in. */
export function Welcome({
  onLanguage,
  ...props
}: AddEpisodeProps & { onLanguage: (next: Language) => void }) {
  return (
    <div className="mx-auto flex max-w-[720px] flex-col gap-6 pt-6 pb-15">
      <div>
        {!languageChosen() && (
          <div className="mb-3">
            <PickLanguage onPick={onLanguage} />
          </div>
        )}
        <h2 className="mb-1.5 text-xl font-semibold">{tr("加第一集", "Add the first episode")}</h2>
        <p className="text-muted-foreground">
          {tr(
            "这个工具把一个动画角色说的每一句台词收集成干净的单人音频，带上台词文字，可以直接拿去训练语音模型。",
            "This tool collects every line one anime character speaks as clean single-speaker audio with its text, ready for training a voice model.",
          )}
        </p>
      </div>
      <AddEpisode {...props} allChecks />
    </div>
  );
}
