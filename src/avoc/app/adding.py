"""Add an episode from the interface. The page fills in the video and subtitle paths, and the server
runs `avoc add` in a separate process, the same command as on the command line.

A separate process keeps the GPU memory of voice separation out of the server, lets the person stop
it, and a crash there does not take the interface down. Only one episode is added at a time. Each
line the command prints is kept, so the page can show the progress.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from avoc.language import LANGUAGE, say
from avoc.pipeline import PROGRESS_MARK

KEEP_LINES = 200
"""How many of the latest output lines are kept for the page."""
COLOR_CODES = re.compile(r"\x1b\[[0-9;]*m")
"""Terminal color codes some libraries put in their warnings."""
PROGRESS_BAR = re.compile(r"\d+%\|")
"""A tqdm progress bar, such as ` 3%|▎   | 44/1429 [02:32<1:26:44, 3.76s/it]`. It redraws itself
with a carriage return, which reading the output in text mode turns into separate lines."""


def clean_path(text: str) -> Path:
    """A path pasted from the file manager often has quotes around it."""
    return Path(text.strip().strip('"').strip("'"))


class Adding:
    def __init__(self, workspace: Path, on_done: Callable[[str], None]) -> None:
        self.workspace = workspace
        self.on_done = on_done
        """Called with the episode name after the command succeeds, before the page is told it is
        done. The server reloads the workspace here."""
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.episode: str | None = None
        self.lines: list[str] = []
        """What the command prints as it goes: one line per step."""
        self.errors: list[str] = []
        """What it prints to stderr: warnings from the libraries it uses, and the reason when it
        fails. The page shows these only when it fails, so the progress stays readable."""
        self.bar = ""
        """The latest progress bar the libraries draw on stderr (voice separation, for example),
        shown on its own line so a long step does not look stuck."""
        self.state = "idle"
        """idle, running, done, failed or stopped."""
        self.started = 0.0
        self.finished = 0.0
        self.ended = threading.Event()
        self.program = [sys.executable, "-m", "avoc"]
        """How to run avoc. Tests swap in a small script."""

    def status(self) -> dict[str, Any]:
        with self.lock:
            end = self.finished if self.state != "running" else time.time()
            return {
                "state": self.state,
                "episode": self.episode,
                "lines": list(self.lines),
                "errors": list(self.errors),
                "bar": self.bar,
                "seconds": round(end - self.started) if self.started else 0,
            }

    def start(
        self,
        video: Path,
        subtitles: Path,
        text_subtitles: Path | None = None,
        offset: float | None = None,
        name: str | None = None,
        styles: list[str] | None = None,
        spoken: str | None = None,
    ) -> dict[str, Any]:
        """Check what can be checked at once, then start `avoc add` in the background. Raises
        ValueError with a reason the person can act on. `styles` are the subtitle styles that hold
        the dialogue; None lets `avoc add` pick them. `spoken` is the language spoken; None lets
        it read the audio track's tag."""
        from avoc.pipeline import NO_TOKEN_HINT, find_episode_by_video, has_hf_token
        from avoc.pipeline import next_episode_name as next_name
        from avoc.project import validate_name

        with self.lock:
            if self.state == "running":
                raise ValueError(
                    say(
                        f"正在加 {self.episode}，等它做完再加下一集",
                        f"{self.episode} is still being added. Wait for it to finish",
                    )
                )
        for path, what in ((video, say("视频", "video")), (subtitles, say("字幕", "subtitles"))):
            if not path.is_file():
                raise ValueError(
                    say(f"找不到{what}文件：{path}", f"cannot find the {what}: {path}")
                )
        if text_subtitles is not None and not text_subtitles.is_file():
            raise ValueError(
                say(
                    f"找不到台词字幕文件：{text_subtitles}",
                    f"cannot find the text subtitles: {text_subtitles}",
                )
            )
        from avoc.stages.subtitle import load_dialogue

        if not load_dialogue(subtitles, styles):
            raise ValueError(say("字幕里没有台词", "there are no dialogue lines in the subtitles"))
        if offset is not None and not math.isfinite(offset):
            raise ValueError(say("字幕偏移必须是一个数", "the subtitle offset must be a number"))
        if offset is None and not has_hf_token():
            raise ValueError(str(NO_TOKEN_HINT))
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise ValueError(
                say(
                    "没找到 FFmpeg。装上它，把 bin 文件夹加进 PATH，再重启 avoc",
                    "FFmpeg was not found. Install it, add its bin folder to PATH, "
                    "and restart avoc",
                )
            )
        name = name or find_episode_by_video(self.workspace, video) or next_name(self.workspace)
        validate_name(name)

        command = [*self.program, "add", str(self.workspace), str(video),
                   "--subs", str(subtitles), "--name", name]  # fmt: skip
        if text_subtitles is not None:
            command += ["--text-subs", str(text_subtitles)]
        if offset is not None:
            command += ["--offset", str(offset)]
        if styles is not None:
            command += ["--styles", ",".join(styles)]
        if spoken is not None:
            command += ["--spoken", spoken]
        environment = {
            **os.environ,
            "AVOC_LANGUAGE": LANGUAGE.get(),
            "AVOC_MARK_PROGRESS": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            # A plain traceback instead of typer's boxed one: its last line is the reason, and
            # the page shows the last lines.
            "_TYPER_STANDARD_TRACEBACK": "1",
        }
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            # Its own process group, so stopping it also stops the FFmpeg it started.
            start_new_session=sys.platform != "win32",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        with self.lock:
            self.process, self.episode, self.lines, self.errors = process, name, [], []
            self.bar = ""
            self.state, self.started, self.finished = "running", time.time(), 0.0
            self.ended = threading.Event()
        threading.Thread(target=self._follow, args=(process, name), daemon=True).start()
        return self.status()

    def _follow(self, process: subprocess.Popen[str], name: str) -> None:
        """Collect the output until the command ends. Then reload the workspace whenever the
        episode got as far as cutting clips, even if it failed or was stopped later, so an
        unfinished episode shows up in the list of episodes not loaded, with a button to carry
        on."""
        assert process.stdout is not None and process.stderr is not None
        errors = threading.Thread(target=self._collect, args=(process.stderr, "errors"))
        errors.start()
        self._collect(process.stdout, "lines")
        errors.join()
        code = process.wait()
        folder = self.workspace / "episodes" / name
        with self.lock:
            stopped = self.state == "stopped"
        if stopped and folder.is_dir() and not (folder / "episode.json").exists():
            # Stopped before the clips were cut: delete the half-built folder, so the next try is
            # not refused. On Windows a file may stay locked for a moment after the process ends.
            for _ in range(10):
                try:
                    shutil.rmtree(folder)
                    break
                except OSError:
                    time.sleep(0.5)
        if (folder / "episode.json").exists():
            try:
                self.on_done(name)
            except Exception as exc:  # The episode is on disk; only loading it failed.
                with self.lock:
                    self.errors.append(str(exc))
                code = code or 1
        with self.lock:
            if self.state == "running":
                self.state = "done" if code == 0 else "failed"
            self.finished = time.time()
        self.ended.set()

    def _collect(self, stream: Any, into: str) -> None:
        for line in stream:
            line = COLOR_CODES.sub("", line).rstrip()
            # Output lines without the mark come from a library printing to the same output.
            target = "errors" if into == "lines" and not line.startswith(PROGRESS_MARK) else into
            line = line.removeprefix(PROGRESS_MARK)
            if PROGRESS_BAR.search(line):
                with self.lock:
                    self.bar = line.strip()
            elif line:
                with self.lock:
                    setattr(self, target, [*getattr(self, target)[-(KEEP_LINES - 1) :], line])

    def stop(self) -> dict[str, Any]:
        """Stop the running command, and wait until it has ended and been cleaned up. Clips and
        voiceprints already made are kept, and adding the same episode again carries on from
        there."""
        with self.lock:
            process = self.process
            if self.state != "running" or process is None:
                return self.status()
            self.state = "stopped"
        if sys.platform == "win32":
            # /T also ends the FFmpeg it started.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
        self.ended.wait(timeout=30)
        return self.status()
