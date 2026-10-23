import { useState } from "react";
import { call } from "../api";
import { tr } from "../language";
import type { Toast } from "../toast";

/* What the box takes. The file window shows only files of this kind at first. */
export type PathKind = "video" | "subtitles" | "folder";

interface PathInputProps {
  kind: PathKind;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  toast: Toast;
}

/* A box for a file or folder path, with "Browse…" after it. A browser never tells a page where a file is, so the
   button asks the local server to open the system's own file window. The window opens in the folder of the path
   in the box, or else where avoc app was started. */
export function PathInput({ kind, value, onChange, placeholder, toast }: PathInputProps) {
  const [open, setOpen] = useState(false);
  const browse = async () => {
    setOpen(true);
    try {
      const { path } = await call<{ path: string | null }>("/api/pick", { kind, current: value });
      if (path) onChange(path);
    } catch (e) {
      toast((e as Error).message, true);
    }
    setOpen(false);
  };
  return (
    <span className="path-input">
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      <button
        type="button"
        disabled={open}
        onClick={browse}
        title={tr("打开系统的选择窗口", "Open the system's file window")}
      >
        {open ? tr("在选择窗口里选…", "Choose in the window…") : tr("浏览…", "Browse…")}
      </button>
    </span>
  );
}
