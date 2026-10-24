"""The "Browse…" button next to each path box. A browser never tells a page where a file is, so the
server, which runs on the same machine, opens the system's own file window and sends back the path
that was picked.

The window is opened by tkinter in a separate process. Tk must own the thread it runs in (on macOS,
the main thread), which a web server's worker thread is not; a separate process also keeps a crash
in the window away from the server.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from avoc.language import say

KINDS = ("video", "subtitles", "folder")
"""What a box takes: a video file, a subtitle file, or a folder."""

VIDEO_PATTERN = "*.mkv *.mp4 *.avi *.mov *.webm *.ts *.m2ts *.flv *.wmv"
SUBTITLE_PATTERN = "*.ass *.ssa *.srt"

PROGRAM = [sys.executable, "-m", "avoc.app.picker"]
"""How to run the window. Tests swap in a small script."""

_open = threading.Lock()
"""Only one window at a time: a second one would hide behind the first."""


def start_folder(current: str, launched: Path) -> Path:
    """Where the window opens: the nearest folder on the path already in the box that exists, so a
    default export folder not made yet opens in the workspace; else the folder `avoc app` was
    started from. A drive root alone does not count."""
    text = current.strip().strip('"').strip("'")
    if text:
        path = Path(text)
        for folder in [path, *path.parents]:
            if folder == Path(folder.anchor):
                break
            if folder.is_dir():
                return folder
    return launched


def pick(kind: str, start: Path, program: list[str] | None = None) -> str | None:
    """Open the window and wait for the person. Returns the path, or None when they cancel."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    every = (say("所有文件", "All files"), "*.*")
    spec = {
        "kind": kind,
        "start": str(start),
        "title": {
            "video": say("选视频文件", "Pick the video file"),
            "subtitles": say("选字幕文件", "Pick the subtitle file"),
            "folder": say("选文件夹", "Pick a folder"),
        }[kind],
        "types": {
            "video": [(say("视频", "Video"), VIDEO_PATTERN), every],
            "subtitles": [(say("字幕", "Subtitles"), SUBTITLE_PATTERN), every],
            "folder": [],
        }[kind],
    }
    if not _open.acquire(blocking=False):
        raise ValueError(
            say(
                "已经开着一个选择窗口，先在那边选好或关掉",
                "a file window is already open; pick or close it first",
            )
        )
    try:
        done = subprocess.run(
            [*(program or PROGRAM), json.dumps(spec)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    finally:
        _open.release()
    if done.returncode != 0:
        reason = (done.stderr.strip().splitlines() or [""])[-1]
        raise ValueError(
            say(
                f"打不开系统的选择窗口（{reason}）。可以直接把路径粘贴进框里",
                f"could not open the system's file window ({reason}). "
                "You can paste the path into the box instead",
            )
        )
    path = json.loads(done.stdout)["path"]
    return str(Path(path)) if path else None


def _window(spec: dict[str, Any]) -> str:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    # Without this the window can open behind the browser.
    root.attributes("-topmost", True)
    root.update()
    if spec["kind"] == "folder":
        path = filedialog.askdirectory(
            parent=root, initialdir=spec["start"], title=spec["title"], mustexist=True
        )
    else:
        path = filedialog.askopenfilename(
            parent=root,
            initialdir=spec["start"],
            title=spec["title"],
            filetypes=[tuple(t) for t in spec["types"]],
        )
    root.destroy()
    return path


if __name__ == "__main__":
    print(json.dumps({"path": _window(json.loads(sys.argv[1])) or None}))
