import type { Roles } from "../api";
import { lowTip, OTHER, type LabelText } from "../clips";
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
  onName: (name: string, low?: boolean) => void;
  onNew: () => void;
}

/* The bar at the bottom: one chip per target character, in a fixed order so the number keys don't move, then
   "Other" and "New character". */
export function Dock({ dock, roles, labelText, canNew, onName, onNew }: DockProps) {
  return (
    <footer className="flex items-center gap-1.5 overflow-x-auto border-t bg-background px-3.5 py-2">
      {dock.map((name, i) => (
        <Chip
          key={name}
          tip={
            i < 9
              ? tr(`按 ${i + 1} 标成 ${name}`, `Press ${i + 1} to label as ${name}`)
              : tr(`标成 ${name}`, `Label as ${name}`)
          }
          onPick={() => onName(name)}
          picture={<Avatar role={roles[name]} name={name} size="md" />}
          hotkey={i < 9 ? String(i + 1) : undefined}
          extra={
            <LowButton
              tip={
                (i < 9
                  ? tr(
                      `按 Shift + ${i + 1} 标成 ${name}·质量低：`,
                      `Press Shift + ${i + 1} to label as ${name}, low quality: `,
                    )
                  : tr(`标成 ${name}·质量低：`, `Label as ${name}, low quality: `)) + lowTip()
              }
              hotkey={i < 9 ? i + 1 : undefined}
              onClick={() => onName(name, true)}
            />
          }
        >
          <RoleName role={roles[name]} name={name} />
        </Chip>
      ))}
      <Chip
        tip={tr("不是任何一个目标角色", "Not any of the target characters")}
        onPick={() => onName(OTHER)}
        picture={<Avatar blank size="md" />}
        hotkey="Q"
      >
        {labelText[OTHER]}
      </Chip>
      <Chip
        off={!canNew}
        tip={tr(
          "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
          "Make a new target character; you can name it later. With video, crop an avatar next",
        )}
        onPick={onNew}
        picture={<Avatar plus size="md" />}
        hotkey="N"
      >
        {tr("新角色", "New character")}
      </Chip>
    </footer>
  );
}
