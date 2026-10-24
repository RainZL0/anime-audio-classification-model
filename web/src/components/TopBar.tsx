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
import { withKeys } from "./Keys";
import { LanguageButton } from "./LanguageButton";
import { Tip } from "./Tip";

/* The tab says "Groups"; its hint says who made them. */
const groupsHint = () =>
  tr(
    "机器按声音自动分的组，可能把几个人混在一组。",
    "Groups the machine made by itself, by voice; a group may mix people. ",
  );

/* The orange count of lines still to do. */
const TODO_COUNT =
  "min-w-4 rounded-full bg-warning/15 px-1.5 text-center text-[11px] leading-4 font-semibold text-warning tabular-nums";

export type View = "groups" | "scene" | "roles" | "export";

/* Groups and Scenes show the episode picked on the left; Characters and Export cover all episodes. */
const EPISODE_VIEWS = (): [View, string, string][] => [
  ["groups", tr("自动分组", "Groups"), "G"],
  ["scene", tr("场景", "Scenes"), "S"],
];
const ALL_VIEWS = (): [View, string, string][] => [
  ["roles", tr("角色", "Characters"), "O"],
  ["export", tr("导出", "Export"), "E"],
];

interface TopBarProps {
  episodes: string[];
  /* Lines still to do in each episode, shown beside it in the episode menu. */
  todo: Record<string, number>;
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
  busy: boolean;
  trainedOn: number;
  targets: number;
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
  /* The count on the Scenes tab means nothing by itself, so its hint says what it counts. */
  const workHint =
    p.work > 0
      ? tr(
          `。${p.episode} 还有 ${p.work} 句要你处理：机器没把握、特征不够认不出，或还没有猜测。「只看要处理的」列的就是这些`,
          `. ${lines(p.work)} in ${p.episode} still to do: the machine isn't sure, too little voice to tell, or no guess yet. "Only to do" lists them`,
        )
      : "";
  const tabs = (list: [View, string, string][]) =>
    list.map(([v, label, key]) => (
      <Tip
        key={v}
        text={withKeys(
          (v === "groups" ? groupsHint() : "") +
            tr(`快捷键 [${key}]`, `Shortcut [${key}]`) +
            (v === "scene" ? workHint : ""),
        )}
      >
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
            <span className={cn("ml-1.5", TODO_COUNT)}>{p.work}</span>
          )}
        </button>
      </Tip>
    ));
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
              /* Only Characters and Export need a word on what the picker changes. */
              perEpisode
                ? undefined
                : tr(
                    "「角色」和「导出」看的是全部集数，换集只影响「自动分组」和「场景」",
                    "Characters and Export cover all episodes; switching only changes Groups and Scenes",
                  )
            }
          >
            <DropdownMenuTrigger
              className={cn(
                "inline-flex h-7 items-center gap-1 rounded-md bg-background px-2 text-sm whitespace-nowrap outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30",
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
                  {/* The same orange count as on the Scenes tab, so the person sees which episodes need work. */}
                  {p.todo[name] > 0 && (
                    <span className={cn("ml-auto", TODO_COUNT)}>{p.todo[name]}</span>
                  )}
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
        <Button variant="ghost" size="sm" className="flex-none" onClick={p.onShowAdding}>
          <Spinner />
          {tr(`正在加 ${p.adding}`, `Adding ${p.adding}`)}
        </Button>
      )}
      <span className="flex-1"></span>
      <Tip text={tr("机器每次标注后都会重新学一次", "The machine retrains after every label")}>
        <span
          className={cn(
            "min-w-0 flex-[0_1_auto] truncate rounded-full border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground",
            p.busy ? "border-primary/40 text-foreground" : "max-[1200px]:hidden",
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
