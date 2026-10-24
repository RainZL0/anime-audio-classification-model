import type { Clip, Status } from "./api";
import { tr } from "./language";

/* "Other": not any of the target characters. It is a human judgment, labeled with Q. Unsure whether it is a
   target, several people talking with no target among them, cheering and sound effects: all get "other". */
export const OTHER = "__other__";

/* "Other" typed as a name, in either language, means the "other" label, not a new character that looks the same. */
export const otherName = (s: string) => ["其他", "other"].includes(s.trim().toLowerCase());

/* How labels that are not character names are shown; for now only "other". */
export type LabelText = Record<string, string>;

export const statusText = (status: Status) =>
  ({
    confirmed: tr("已确认", "Confirmed"),
    auto: tr("机器有把握", "Confident"),
    review: tr("待确认", "Check"),
    novoice: tr("特征不够", "Too little voice"),
    unlabeled: tr("还没有模型", "No model yet"),
    skipped: tr("已跳过", "Skipped"),
  })[status];

/* The labels stay plain; the exact rules are in the hints, for those who want them. Each hint names the other
   kind, since both are about short lines. */
export const novoiceTip = () =>
  tr(
    "规则：短于 0.5 秒，声音太少，算不出声纹（机器用来认声音的一组数字），所以机器不猜。前后 0.5 秒内有别的台词，可能是对话的一部分，所以不跳过，请直接选人",
    "Rule: shorter than 0.5 seconds, too little sound to make a voiceprint (the numbers the machine uses to recognize a voice), so the machine makes no guess. Another line is within 0.5 seconds, so it may be part of a conversation and is not skipped: pick the character yourself",
  );
export const skippedTip = () =>
  tr(
    "规则：短于 1 秒，前后 0.5 秒内又没有别的台词，训练用不上，不算要处理的。前后有台词的短句不跳过，显示为「特征不够」",
    'Rule: shorter than 1 second with no other line within 0.5 seconds: no use for training, and not work to do. A short line with another line close by is not skipped; it shows as "Too little voice"',
  );

export const NEEDS_WORK = new Set<Status>(["review", "novoice", "unlabeled"]);

/* Each target character has two choices: clean, and "low quality" (Shift + number). Only targets have it;
   "other" is never exported anyway. There used to be a separate "several people", now merged into low quality. */
export const lowTip = () =>
  tr(
    "背景音太重、有人同时出声之类，不能进干净数据集。不拿来认人，导出时跳过",
    "Too much background sound, someone talking at the same time and so on: not fit for a clean dataset. " +
      "Not used to recognize anyone, and skipped on export",
  );

export const confidence = (clip: Clip) => clip.guess[0]?.p ?? 0;

export const chanceOf = (clip: Clip, name: string | undefined) =>
  clip.guess.find((g) => g.name === name)?.p ?? 0;

/* The target character the machine finds most likely. "Other" does not count. */
export const bestTarget = (clip: Clip) => clip.guess.find((g) => g.name !== OTHER);

export interface Who {
  name: string;
  human: boolean;
  p?: number;
}

/* Who a clip belongs to now: the human label first, else the machine's top guess. */
export function whoOf(clip: Clip): Who | null {
  if (clip.label) return { name: clip.label, human: true };
  if (clip.guess.length) return { name: clip.guess[0].name, human: false, p: clip.guess[0].p };
  return null;
}

/* To check in the Characters view: given to this character by the machine, not yet confirmed, least sure first. */
export const pendingOf = (clips: Clip[]) =>
  clips.filter((c) => !c.label && !c.maybe).sort((a, b) => confidence(a) - confidence(b));

/* Maybe missed: not given to this character, but with a fair chance of being them. The server already sorted
   them most likely first; they are not re-sorted after retraining, so the list doesn't jump under your hand. */
export const maybeListOf = (clips: Clip[]) => clips.filter((c) => c.maybe);

/* Confirmed lines in the server's order: by time for a target, most like some target first for "other". */
export const confirmedOf = (clips: Clip[], role: string | null) =>
  clips.filter((c) => c.label === role);
