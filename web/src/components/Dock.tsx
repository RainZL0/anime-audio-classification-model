import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import type { Roles } from "../api";
import { lowTip, newTip, OTHER, type LabelText } from "../clips";
import { tr } from "../language";
import { Avatar } from "./Avatar";
import { Chip, LowButton } from "./Chip";
import { RoleName } from "./RoleName";

interface DockProps {
  dock: string[];
  roles: Roles;
  labelText: LabelText;
  /* Whether there is a line to label, which "New character" needs. */
  canNew: boolean;
  /* Whether there is a line to label: one selected, or lines ticked in Groups. */
  canLabel: boolean;
  onName: (name: string, low?: boolean) => void;
  onNew: () => void;
  canUndo: boolean;
  onUndo: () => void;
}

/* The bar at the bottom: one chip per target character, in a fixed order so the number keys don't move, then
   "Other" and "New character". */
export function Dock({
  dock,
  roles,
  labelText,
  canNew,
  canLabel,
  onName,
  onNew,
  canUndo,
  onUndo,
}: DockProps) {
  return (
    <footer className="flex items-center gap-1.5 overflow-x-auto border-t bg-background px-3.5 py-2">
      {dock.map((name, i) => (
        <Chip
          key={name}
          off={!canLabel}
          onPick={() => onName(name)}
          picture={<Avatar role={roles[name]} name={name} size="md" />}
          hotkey={i < 9 ? String(i + 1) : undefined}
          extra={
            <LowButton
              disabled={!canLabel}
              tip={lowTip()}
              hotkey={i < 9 ? i + 1 : undefined}
              onClick={() => onName(name, true)}
            />
          }
        >
          <RoleName role={roles[name]} name={name} />
        </Chip>
      ))}
      <Chip
        off={!canLabel}
        tip={tr("不是任何一个目标角色", "Not any of the target characters")}
        onPick={() => onName(OTHER)}
        picture={<Avatar blank size="md" />}
        hotkey="Q"
      >
        {labelText[OTHER]}
      </Chip>
      <Chip
        off={!canNew}
        tip={newTip()}
        onPick={onNew}
        picture={<Avatar plus size="md" />}
        hotkey="N"
      >
        {tr("新角色", "New character")}
      </Chip>
      {/* Undo goes back on the last label, so it sits with the choices that label. */}
      <span className="flex-1"></span>
      <Button variant="ghost" size="sm" className="flex-none" disabled={!canUndo} onClick={onUndo}>
        {tr("撤销", "Undo")} <Kbd>Z</Kbd>
      </Button>
    </footer>
  );
}
