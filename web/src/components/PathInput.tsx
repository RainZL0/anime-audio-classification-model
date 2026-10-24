import { cn } from "cn";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
export function PathInput({
  kind,
  value,
  onChange,
  placeholder,
  toast,
  className,
}: PathInputProps & { className?: string }) {
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
    <span className={cn("flex min-w-0 gap-1.5", className)}>
      <Input
        className="min-w-0 flex-1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      <Button type="button" variant="outline" disabled={open} onClick={browse}>
        {open ? tr("在选择窗口里选…", "Choose in the window…") : tr("浏览…", "Browse…")}
      </Button>
    </span>
  );
}
