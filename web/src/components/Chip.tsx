import { cn } from "cn";
import type { ReactNode } from "react";
import { tr } from "../language";
import { Tip } from "./Tip";

/* "Low quality" inside a character's chip or row: the same character, but not fit for a clean dataset (red, see
   docs/UI_DESIGN.md#color). `hotkey` is the number of the character, shown as Shift + number. */
export function LowButton({
  hotkey,
  tip,
  disabled,
  onClick,
}: {
  hotkey?: number;
  tip: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Tip text={tip}>
      <button
        type="button"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        className="ml-0.5 inline-flex items-center gap-1 rounded-full border border-destructive/20 px-1.5 text-[11px] whitespace-nowrap text-destructive transition-colors hover:border-destructive disabled:opacity-45 disabled:hover:border-destructive/20"
      >
        {tr("质量低", "Low quality")}
        {hotkey != null && <span className="font-mono text-muted-foreground">⇧{hotkey}</span>}
      </button>
    </Tip>
  );
}

/* A "who is it" choice: a rounded button with a small picture, a name and its key (see docs/UI_DESIGN.md). The same
   look in the bottom bar and under each group. `top` marks the machine's guess; `off` grays it out when there is
   nothing to label yet, without hiding it. */
export function Chip({
  picture,
  children,
  hotkey,
  tip,
  top,
  off,
  small,
  onPick,
  extra,
}: {
  picture: ReactNode;
  children: ReactNode;
  hotkey?: string;
  tip?: ReactNode;
  top?: boolean;
  off?: boolean;
  small?: boolean;
  onPick: () => void;
  /* More buttons inside the chip, such as "Low quality". */
  extra?: ReactNode;
}) {
  return (
    <Tip text={tip}>
      <div
        role="button"
        tabIndex={-1}
        aria-disabled={off || undefined}
        onClick={() => !off && onPick()}
        className={cn(
          "inline-flex flex-none cursor-pointer items-center gap-1.5 rounded-full border bg-background whitespace-nowrap transition-colors hover:border-primary",
          small ? "py-0.5 pr-2.5 pl-0.5 text-[13px]" : "py-1 pr-2.5 pl-1",
          top && "border-primary/40 bg-accent",
          off && "cursor-default opacity-45 hover:border-border",
        )}
      >
        {picture}
        {children}
        {hotkey && <span className="font-mono text-[11px] text-muted-foreground">{hotkey}</span>}
        {extra}
      </div>
    </Tip>
  );
}
