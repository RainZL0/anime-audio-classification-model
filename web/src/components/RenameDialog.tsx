import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { otherName } from "../clips";
import { tr } from "../language";
import { Note } from "./Notes";

/* ───────────── Naming, renaming or merging a character ───────────── */

/* Typing the name of another character merges this one into it, which the dialog says before it is done. */
export function RenameDialog({
  name,
  unnamed,
  others,
  onSave,
  onClose,
}: {
  name: string;
  /* It still has a made-up name such as "Character 1": the box starts empty. */
  unnamed: boolean;
  /* The names of the other characters. */
  others: string[];
  onSave: (next: string) => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState(unnamed ? "" : name);
  const box = useRef<HTMLInputElement>(null);
  const next = typed.trim();
  const problem = otherName(next)
    ? tr("「其他」是标签，不能当名字", '"Other" is a label, not a name')
    : "";
  const merge = !problem && others.includes(next);
  const usable = !!next && next !== name && !problem;
  const save = (e?: FormEvent) => {
    e?.preventDefault();
    if (usable) onSave(next);
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        initialFocus={box}
        className="gap-3 p-4 sm:max-w-[440px]"
      >
        <DialogTitle className="text-base font-semibold">
          {unnamed
            ? tr(`给「${name}」起名字`, `Name "${name}"`)
            : tr(`改名或合并「${name}」`, `Rename or merge "${name}"`)}
        </DialogTitle>
        <form onSubmit={save} className="flex flex-col gap-2">
          <Input
            ref={box}
            value={typed}
            aria-invalid={!!problem || undefined}
            className="h-9 text-[15px] md:text-[15px]"
            onFocus={(e) => e.currentTarget.select()}
            onChange={(e) => setTyped(e.target.value)}
          />
          {problem ? (
            <p className="text-xs text-destructive">{problem}</p>
          ) : merge ? (
            <Note warn>
              {tr(
                `已经有「${next}」了：保存会把「${name}」并进去，它的台词都归「${next}」。按 Z 可以撤销。`,
                `"${next}" already exists: saving merges "${name}" into it, and all its lines become "${next}"'s. Z undoes it.`,
              )}
            </Note>
          ) : (
            <Note>
              {tr(
                "填一个已有角色的名字，就是把两个角色合并。",
                "Typing the name of another character merges the two.",
              )}
            </Note>
          )}
          <DialogFooter className="mt-1">
            <Button type="button" variant="ghost" onClick={onClose}>
              {tr("取消", "Cancel")} <Kbd>Esc</Kbd>
            </Button>
            <Button type="submit" disabled={!usable}>
              {merge ? tr("合并", "Merge") : tr("保存", "Save")} <Kbd>Enter</Kbd>
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
