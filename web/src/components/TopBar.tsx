import { cn } from "cn";
import { ChevronDownIcon, MoonIcon, PlusIcon, SunIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { lines, many, tr } from "../language";
import { LanguageButton } from "./LanguageButton";
import { Tip } from "./Tip";

export type View = "groups" | "scene" | "roles" | "export";

/* Groups and Scenes show the episode picked on the left; Characters and Export cover all episodes. */
const EPISODE_VIEWS = (): [View, string, string][] => [
  ["groups", tr("起步分组", "Groups"), "G"],
  ["scene", tr("场景", "Scenes"), "S"],
];
const ALL_VIEWS = (): [View, string, string][] => [
  ["roles", tr("角色", "Characters"), "O"],
  ["export", tr("导出", "Export"), "E"],
];

interface TopBarProps {
  episodes: string[];
  episode: string | null;
  setEpisode: (name: string) => void;
  onAdd: () => void;
  /* How many episodes were left unfinished, shown beside "Add an episode". */
  unfinished: number;
  view: View;
  setView: (v: View) => void;
  /* Lines left to check in this episode, shown on the Scenes tab. */
  work: number;
  /* The episode being added, while its dialog is closed. */
  adding: string | null;
  onShowAdding: () => void;
  /* This episode's progress, as parts of 1: confirmed, and the machine's confident guesses. */
  progress: { done: number; auto: number };
  busy: boolean;
  trainedOn: number;
  targets: number;
  canUndo: boolean;
  onUndo: () => void;
  dark: boolean;
  onTheme: () => void;
  onLanguage: () => void;
  onGuide: () => void;
  onHelp: () => void;
}

/* A box of view tabs, in the look of shadcn's tabs. They stay plain buttons: each one only switches the view. */
function TabBox({ children }: { children: ReactNode }) {
  return (
    <nav className="flex flex-none items-center gap-0.5 rounded-lg bg-muted p-[3px]">
      {children}
    </nav>
  );
}

/* The bar at the top. What is left out as the window narrows follows docs/UI_DESIGN.md#layout. */
export function TopBar(p: TopBarProps) {
  const perEpisode = EPISODE_VIEWS().some(([v]) => v === p.view);
  const tabs = (list: [View, string, string][]) =>
    list.map(([v, label, key]) => (
      <Tip key={v} text={tr(`快捷键 ${key}`, `Shortcut ${key}`)}>
        <button
          type="button"
          aria-pressed={p.view === v}
          onClick={() => p.setView(v)}
          className={cn(
            "inline-flex h-7 items-center rounded-md px-3 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
            p.view === v && "bg-background text-foreground shadow-sm dark:bg-input/30",
          )}
        >
          {label}
          {v === "scene" && p.work > 0 && (
            <span className="ml-1.5 text-[11px] text-warning tabular-nums">{p.work}</span>
          )}
        </button>
      </Tip>
    ));
  const pct = Math.round(p.progress.done * 100);
  const themeText = p.dark
    ? tr("换成白天配色", "Switch to light colors")
    : tr("换成夜间配色", "Switch to dark colors");
  return (
    <header className="flex items-center gap-2.5 border-b bg-background px-[18px] py-2.5 max-[860px]:gap-1 max-[860px]:px-2.5">
      <div className="flex flex-none items-center gap-2 font-semibold tracking-wide">
        <span className="size-2.5 rounded-full bg-primary"></span>avoc
      </div>
      <TabBox>
        <DropdownMenu>
          <Tip
            text={
              perEpisode
                ? tr("换一集", "Switch episode")
                : tr(
                    "「角色」和「导出」看的是全部集数，换集只影响「起步分组」和「场景」",
                    "Characters and Export cover all episodes; switching only changes Groups and Scenes",
                  )
            }
          >
            <DropdownMenuTrigger
              className={cn(
                "inline-flex h-7 items-center gap-1 rounded-md bg-background px-2 text-sm whitespace-nowrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30",
                perEpisode ? "font-semibold" : "text-muted-foreground",
              )}
            >
              {p.episode}
              <ChevronDownIcon className="size-3.5 opacity-60" />
            </DropdownMenuTrigger>
          </Tip>
          {/* Focus goes nowhere after a pick, so the arrow keys meant for the next line don't open the menu again. */}
          <DropdownMenuContent finalFocus={false} className="w-auto min-w-40">
            <DropdownMenuRadioGroup value={p.episode} onValueChange={(v) => p.setEpisode(v)}>
              {p.episodes.map((name) => (
                <DropdownMenuRadioItem key={name} value={name} closeOnClick>
                  {name}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={p.onAdd}>
              <PlusIcon />
              {tr("加一集…", "Add an episode…")}
              {p.unfinished > 0 && (
                <span className="text-xs text-warning">
                  {tr(`（${p.unfinished} 集没做完）`, `(${p.unfinished} unfinished)`)}
                </span>
              )}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {tabs(EPISODE_VIEWS())}
      </TabBox>
      <TabBox>
        <span className="pr-1.5 pl-2 text-xs whitespace-nowrap text-muted-foreground max-[920px]:hidden">
          {tr("全部集数", "All episodes")}
        </span>
        {tabs(ALL_VIEWS())}
      </TabBox>
      {p.adding && (
        <Tip text={tr("点开看进度", "Click to see the progress")}>
          <Button variant="ghost" size="sm" className="flex-none" onClick={p.onShowAdding}>
            <Spinner />
            {tr(`正在加 ${p.adding}`, `Adding ${p.adding}`)}
          </Button>
        </Tip>
      )}
      <span className="flex-1"></span>
      {perEpisode && (
        <Tip
          text={tr(
            "绿色是已经确认的，浅绿是机器有把握的",
            "Green is confirmed, light green is the machine's confident ones",
          )}
        >
          <div className="flex min-w-0 flex-[0_1_auto] items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
            <span className="min-w-0 truncate max-[1200px]:hidden">
              {tr(`${p.episode}：确认 ${pct}%`, `${p.episode}: ${pct}% confirmed`)}
            </span>
            <div className="flex h-1.5 w-40 min-w-10 flex-[0_1_160px] overflow-hidden rounded-full bg-muted">
              <i className="block bg-success" style={{ width: `${p.progress.done * 100}%` }}></i>
              <i className="block bg-success/35" style={{ width: `${p.progress.auto * 100}%` }}></i>
            </div>
          </div>
        </Tip>
      )}
      <Tip text={tr("机器每次标注后都会重新学一次", "The machine retrains after every label")}>
        <span
          className={cn(
            "min-w-0 flex-[0_1_auto] truncate rounded-full border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground",
            p.busy ? "border-primary/40 text-foreground" : "max-[1400px]:hidden",
          )}
        >
          {p.busy
            ? tr("正在重新学习…", "Retraining…")
            : p.trainedOn
              ? tr(
                  `机器学过 ${p.trainedOn} 句 · ${p.targets} 个目标角色`,
                  `Trained on ${lines(p.trainedOn)} · ${many(p.targets, "target")}`,
                )
              : tr("机器还没学过", "Not trained yet")}
        </span>
      </Tip>
      <Tip text={tr("撤销上一步", "Undo the last step")}>
        <Button
          variant="ghost"
          size="sm"
          className="flex-none"
          disabled={!p.canUndo}
          onClick={p.onUndo}
        >
          {tr("撤销", "Undo")} <Kbd>Z</Kbd>
        </Button>
      </Tip>
      <LanguageButton onSwitch={p.onLanguage} />
      <Tip text={themeText}>
        <Button
          variant="ghost"
          size="icon-sm"
          className="flex-none"
          onClick={p.onTheme}
          aria-label={themeText}
        >
          {p.dark ? <SunIcon /> : <MoonIcon />}
        </Button>
      </Tip>
      <Tip
        text={tr("四个页面是做什么的，怎么上手", "What the four views are for, and how to start")}
      >
        <Button variant="ghost" size="sm" className="flex-none" onClick={p.onGuide}>
          {tr("指南", "Guide")}
        </Button>
      </Tip>
      <Tip text={tr("全部快捷键", "All shortcuts")}>
        <Button
          variant="ghost"
          size="sm"
          className="flex-none"
          onClick={p.onHelp}
          aria-label={tr("全部快捷键", "All shortcuts")}
        >
          <Kbd>?</Kbd>
        </Button>
      </Tip>
    </header>
  );
}
