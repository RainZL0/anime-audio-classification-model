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
      name: tr("分组", "Groups"),
      key: "G",
      scope: oneEpisode,
      what: tr(
        "机器把听起来像同一个人的台词分成一组。",
        "The machine puts lines that sound like the same person into one group.",
      ),
      when: (
        <>
          {tr(
            "找到你要的角色的一组，勾上这些台词，点「新角色」（",
            'Find a group of the character you want, tick those lines, and press "New character" (',
          )}
          <Kbd>N</Kbd>
          {tr("）；别人的按 ", "); label other people's with ")}
          <Kbd>Q</Kbd>
          {tr(
            " 标「其他」。一组混着几个人时，分几次勾、几次标。这个角色确认满 10 句、别人也标了几句以后，机器就开始猜了。",
            ' ("Other"). When a group mixes several people, tick and label them in turns. Once 10 lines of the character are confirmed and a few others are labeled, the machine starts guessing.',
          )}
        </>
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
          {tr(
            "（其他）。背景太吵或者有人同时说话的，按 ",
            " (Other). For loud background sound or two people at once, press ",
          )}
          <Kbd>Shift</Kbd>
          {tr(
            " + 数字标成「质量低」，不拿来训练，也不导出。",
            " + the number to mark it low quality; it is not used for training or exported.",
          )}
        </>
      ),
    },
    {
      name: tr("角色", "Characters"),
      key: "O",
      scope: allEpisodes,
      what: tr(
        "机器归给一个角色的所有台词，最没把握的排在前面；下面还有可能漏掉的。",
        "Everything the machine gave one character, least sure first, and below it the lines it may have missed.",
      ),
      when: (
        <>
          {tr(
            "机器开始猜以后：听出错的改掉，剩下的按 ",
            "Once the machine is guessing: fix the wrong ones, then press ",
          )}
          <Kbd>Shift+Enter</Kbd>
          {tr(
            " 一起确认。再看看下面「可能漏掉」的。",
            ' to confirm the rest. Then look at "Maybe missed" below.',
          )}
        </>
      ),
    },
    {
      name: tr("导出", "Export"),
      key: "E",
      scope: allEpisodes,
      what: tr(
        "把角色的台词写成 GPT-SoVITS 或 RVC 用的数据集。",
        "Writes a character's lines as a dataset for GPT-SoVITS or RVC.",
      ),
      when: tr(
        "标够了以后，选角色和格式导出。GPT-SoVITS 要的台词得是视频里说的语言，取自主字幕。",
        "When you have enough, pick the character and the format, and export. GPT-SoVITS needs the words in the language spoken, taken from the main subtitles.",
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
              "你只需要给想收集的角色（目标角色）起名，其他人一律标「其他」。每标一句，机器马上重新学一次，再去猜剩下的台词。",
              'You only name the characters you want to collect (the target characters); everyone else is "Other". After every label the machine retrains and guesses the rest again.',
            )}
          </DialogDescription>
        </DialogHeader>
        {/* The four views in the order they are used, so the cards are also the steps. */}
        <ol className="grid grid-cols-2 gap-2.5 text-[13px]">
          {views.map((v, i) => (
            <li className="flex flex-col gap-1 rounded-lg border px-3 py-2.5" key={v.key}>
              <div className="flex items-center gap-1.5">
                <b className="font-semibold">
                  {i + 1}. {v.name}
                </b>{" "}
                <Kbd>{v.key}</Kbd>
                <Note className="ml-auto">{v.scope}</Note>
              </div>
              <div>{v.what}</div>
              <Note>{v.when}</Note>
            </li>
          ))}
        </ol>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {tr("关掉", "Close")}
          </Button>
          <Button onClick={onStart}>{tr("从「分组」开始", "Start in Groups")}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
