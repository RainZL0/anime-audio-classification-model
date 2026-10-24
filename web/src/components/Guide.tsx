import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { tr } from "../language";
import { Note } from "./Notes";

/* ───────────── Getting started ───────────── */

/* Opened by itself the first time a workspace with episodes is opened and nothing is labeled yet; afterwards from
   the Guide button in the top bar or the shortcuts dialog. */
export const GUIDE_SEEN = "guide-seen";

interface ViewCard {
  name: string;
  key: string;
  scope: string;
  what: string;
  when: ReactNode;
}

export function Guide({ onClose, onStart }: { onClose: () => void; onStart: () => void }) {
  const oneEpisode = tr("一集", "One episode");
  const allEpisodes = tr("全部集数", "All episodes");
  const views: ViewCard[] = [
    {
      name: tr("起步分组", "Groups"),
      key: "G",
      scope: oneEpisode,
      what: tr(
        "机器把听起来像同一个人的句子放成一组。",
        "The machine puts lines that sound like the same person into one group.",
      ),
      when: tr(
        "刚开始、什么都还没标的时候用：勾上同一个人的句子，一次给整组起名。",
        "Use it first, while nothing is labeled: tick one person's lines and name the whole group at once.",
      ),
    },
    {
      name: tr("场景", "Scenes"),
      key: "S",
      scope: oneEpisode,
      what: tr(
        "这一集的每句台词按顺序排，左边放画面，看得到是谁在说。",
        "Every line of the episode in order, with the picture on the left, so you can see who is speaking.",
      ),
      when: (
        <>
          {tr("一句一句过：机器猜对了按 ", "Go line by line: when the guess is right press ")}
          <Kbd>Enter</Kbd>
          {tr("，不对就按数字选人，或者 ", ", otherwise pick the person with a number, or ")}
          <Kbd>Q</Kbd>
          {tr("（其他）。", " (Other).")}
        </>
      ),
    },
    {
      name: tr("角色", "Characters"),
      key: "O",
      scope: allEpisodes,
      what: tr(
        "机器归给一个角色的所有句子，最没把握的排在前面；下面还有可能漏掉的。",
        "Everything the machine gave one character, least sure first, and below it the lines it may have missed.",
      ),
      when: (
        <>
          {tr(
            "机器开始会猜以后用：听出错的改掉，剩下的按 ",
            "Once the machine is guessing: fix the wrong ones, then press ",
          )}
          <Kbd>Shift+Enter</Kbd>
          {tr(" 一起确认。", " to confirm the rest.")}
        </>
      ),
    },
    {
      name: tr("导出", "Export"),
      key: "E",
      scope: allEpisodes,
      what: tr(
        "把角色的句子写成 GPT-SoVITS、Style-Bert-VITS2 或 RVC 用的数据集。",
        "Writes a character's lines as a dataset for GPT-SoVITS, Style-Bert-VITS2 or RVC.",
      ),
      when: tr(
        "标够了以后用。要带文字的格式，台词得是视频里说的语言，这里能给每集补配字幕。",
        "When you have enough. Formats with text need the words in the language spoken; you can attach subtitles for each episode here.",
      ),
    },
  ];
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="max-h-[84vh] overflow-y-auto sm:max-w-[760px]"
      >
        <DialogHeader>
          <DialogTitle className="font-semibold">{tr("上手指南", "Getting started")}</DialogTitle>
          <DialogDescription className="text-[13px]">
            {tr(
              "你只需要给想收集的角色（目标角色）起名，其他人一律标「其他」。每标一句，机器马上重新学一次，再去猜剩下的句子。",
              'You only name the characters you want to collect (the target characters); everyone else is "Other". After every label the machine retrains and guesses the rest again.',
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-2.5 text-[13px]">
          {views.map((v) => (
            <div className="flex flex-col gap-1 rounded-lg border px-3 py-2.5" key={v.key}>
              <div className="flex items-center gap-1.5">
                <b className="font-semibold">{v.name}</b> <Kbd>{v.key}</Kbd>
                <Note className="ml-auto">{v.scope}</Note>
              </div>
              <div>{v.what}</div>
              <Note>{v.when}</Note>
            </div>
          ))}
        </div>
        <div>
          <h3 className="mb-1 text-sm font-semibold">{tr("五步上手", "Five steps")}</h3>
          <ol className="list-decimal space-y-1 pl-5 text-[13px] text-muted-foreground">
            <li>
              {tr(
                "在「起步分组」里找到你要的角色的一组，勾上这些句子，点「新角色」（",
                'In Groups, find a group of the character you want, tick those lines, and press "New character" (',
              )}
              <Kbd>N</Kbd>
              {tr(
                "）起名。别人的句子按 ",
                ") to name the character. Label other people's lines with ",
              )}
              <Kbd>Q</Kbd>
              {tr(" 标「其他」。", ' ("Other").')}
            </li>
            <li>
              {tr(
                "先标二三十句这个角色的、再标一些别人的，机器就能开始猜了。右上角显示它学过几句。",
                "Label twenty or thirty of the character's lines and some of other people's, and the machine starts guessing. The top right shows how many lines it has learned from.",
              )}
            </li>
            <li>
              {tr(
                "到「场景」里一句句过。背景太吵或者有人同时说话的，按 ",
                "Go through Scenes line by line. For lines with loud background sound or someone talking at the same time, press ",
              )}
              <Kbd>Shift</Kbd>
              {tr(
                " + 数字标成「质量低」，它们不拿来训练，也不导出。",
                " + the number to mark them low quality; they are not used for training or exported.",
              )}
            </li>
            <li>
              {tr(
                "到「角色」里看机器归给这个角色的句子，改掉错的，其余一起确认。再看看下面「可能漏掉」的。",
                'In Characters, check the lines the machine gave the character, fix the wrong ones and confirm the rest. Then look at "Maybe missed" below.',
              )}
            </li>
            <li>
              {tr(
                "到「导出」里选角色和格式，导出。",
                "In Export, pick the character and the format, and export.",
              )}
            </li>
          </ol>
        </div>
        <Note>
          {tr("标错了按 ", "Made a mistake? ")}
          <Kbd>Z</Kbd>
          {tr(" 撤销，可以一直往回撤。按 ", " undoes, as far back as you like. ")}
          <Kbd>?</Kbd>
          {tr(
            " 看全部快捷键。这份指南随时能从顶栏的「指南」再打开。",
            " shows every shortcut. Open this guide again from Guide in the top bar.",
          )}
        </Note>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {tr("关掉", "Close")}
          </Button>
          <Button onClick={onStart}>{tr("从「起步分组」开始", "Start in Groups")}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
