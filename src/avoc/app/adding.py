"""Add an episode from the interface. The page fills in the video and subtitle paths, and the server
runs `avoc add` in a separate process, the same command as on the command line.

A separate process keeps the GPU memory of voice separation out of the server, lets the person stop
it, and a crash there does not take the interface down. Only one episode is added at a time. Each
line the command prints is kept, so the page can show the progress.

The files each episode was started with are written to `adding.json` in the workspace and kept
until the episode is added. So an episode that was stopped, failed, or cut off when the server
restarted is still listed after a restart, and can be carried on with the same files.
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
RECORD = "adding.json"
"""In the workspace: episode name -> the files and choices it was started with."""
STOP_WITH_INTERFACE = "AVOC_STOP_WITH_INTERFACE"
"""Set for the `avoc add` the interface starts, to the server's process number; see
`stop_with_interface`."""


def clean_path(text: str) -> Path:
    """A path pasted from the file manager often has quotes around it."""
    return Path(text.strip().strip('"').strip("'"))


def stop_with_interface(server: int) -> None:
    """Called in `avoc add` when the interface started it. When the server process ends (a
    restart under `--reload`, a closed terminal, or a crash), stop as if Ctrl+C was pressed, so
    the usual clean-up runs (a half-cut folder is deleted) and the command does not run on unseen,
    holding the GPU.

    On Windows, wait on the server process itself. Waiting on the input instead (the server keeps
    it open and never writes to it, so it ends only with the server) makes numpy's OpenBLAS hang
    forever while it loads: a thread blocked reading a pipe stops it from starting. Elsewhere,
    wait for the input to end."""
    import _thread

    def watch() -> None:
        if sys.platform == "win32":
            import ctypes

            synchronize, forever = 0x00100000, 0xFFFFFFFF
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            handle = kernel.OpenProcess(synchronize, False, server)
            if not handle:  # Already gone.
                _thread.interrupt_main()
                return
            kernel.WaitForSingleObject(handle, forever)
        else:
            sys.stdin.buffer.read()
        _thread.interrupt_main()

    threading.Thread(target=watch, daemon=True).start()


def _remove(folder: Path) -> bool:
    """Delete a half-built episode folder. On Windows a file may stay locked for a moment after the
    process that wrote it ends."""
    for _ in range(10):
        try:
            shutil.rmtree(folder)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.5)
    return not folder.exists()


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
        self._records_lock = threading.Lock()

    def _folder(self, name: str) -> Path:
        return self.workspace / "episodes" / name

    def _cut(self, name: str) -> bool:
        """Whether the slowest step, cutting the clips, is done: it writes episode.json last."""
        return (self._folder(name) / "episode.json").exists()

    def _records(self) -> dict[str, dict[str, Any]]:
        from avoc.project import read_json

        path = self.workspace / RECORD
        return read_json(path) if path.is_file() else {}

    def _change_records(self, change: Callable[[dict[str, dict[str, Any]]], None]) -> None:
        from avoc.project import write_json

        with self._records_lock:
            records = self._records()
            change(records)
            path = self.workspace / RECORD
            if records:
                self.workspace.mkdir(parents=True, exist_ok=True)
                write_json(path, records)
            else:
                path.unlink(missing_ok=True)

    def not_cut(self) -> list[str]:
        """Episodes started earlier whose clips were never cut: they cannot be loaded, so they are
        listed only from the record. The one being added now is left out."""
        with self.lock:
            running = self.episode if self.state == "running" else None
        return [n for n in self._records() if n != running and not self._cut(n)]

    def drop_records(self, names: set[str]) -> None:
        """Forget the record of these episodes: added, given up, or loading in full (including
        ones finished from the command line)."""

        def drop(records: dict[str, dict[str, Any]]) -> None:
            for name in names & records.keys():
                del records[name]

        if names & self._records().keys():
            self._change_records(drop)

    def status(self) -> dict[str, Any]:
        with self.lock:
            end = self.finished if self.state != "running" else time.time()
            return {
                "state": self.state,
                "episode": self.episode,
                "cut": self.episode is not None and self._cut(self.episode),
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
        display_subtitles: Path | None = None,
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
        if display_subtitles is not None and not display_subtitles.is_file():
            raise ValueError(
                say(
                    f"找不到辅助字幕文件：{display_subtitles}",
                    f"cannot find the secondary subtitles: {display_subtitles}",
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
            from avoc.doctor import ffmpeg_howto

            raise ValueError(say("没找到 FFmpeg。", "FFmpeg was not found. ") + ffmpeg_howto())
        records = self._records()
        recorded = next((n for n, r in records.items() if r["video"] == str(video.resolve())), None)
        name = (
            name or find_episode_by_video(self.workspace, video) or recorded
            or next_name(self.workspace)
        )  # fmt: skip
        validate_name(name)
        folder = self._folder(name)
        # A folder left half-built by a run that was cut off before it could clean up. The record
        # says it was ours, and nothing is running now, so it can go.
        if name in records and folder.is_dir() and not self._cut(name) and not _remove(folder):
            raise ValueError(
                say(
                    f"删不掉 {name} 上次做了一半的文件，可能上次的处理还没完全停下。等一会儿再试",
                    f"Cannot delete the half-built files of {name}; the last run may not have "
                    "fully stopped yet. Try again in a moment",
                )
            )

        command = [*self.program, "add", str(self.workspace), str(video),
                   "--subs", str(subtitles), "--name", name]  # fmt: skip
        if text_subtitles is not None:
            command += ["--text-subs", str(text_subtitles)]
        if display_subtitles is not None:
            command += ["--display-subs", str(display_subtitles)]
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
            STOP_WITH_INTERFACE: str(os.getpid()),
        }

        def remember(records: dict[str, dict[str, Any]]) -> None:
            def path(p: Path | None) -> str | None:
                return str(p.resolve()) if p is not None else None

            records[name] = {
                "video": path(video),
                "subtitles": path(subtitles),
                "text_subtitles": path(text_subtitles),
                "display_subtitles": path(display_subtitles),
                "offset": offset,
                "styles": styles,
                "spoken": spoken,
            }

        self._change_records(remember)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
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
        if process.stdin is not None:
            process.stdin.close()
        folder = self._folder(name)
        with self.lock:
            stopped = self.state == "stopped"
        if stopped and folder.is_dir() and not self._cut(name):
            # Stopped before the clips were cut: delete the half-built folder, so the next try is
            # not refused.
            _remove(folder)
        if self._cut(name):
            try:
                self.on_done(name)
            except Exception as exc:  # The episode is on disk; only loading it failed.
                with self.lock:
                    self.errors.append(str(exc))
                code = code or 1
        if code == 0 and not stopped:
            self.drop_records({name})
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

    def carry_on(self, name: str) -> dict[str, Any]:
        """Start an unfinished episode again with the files it was started with: from the record,
        or, for an episode added before there was one, from its episode.json."""
        from avoc.project import read_json, validate_name

        validate_name(name)
        record = self._records().get(name)
        meta = read_json(self._folder(name) / "episode.json") if self._cut(name) else None
        if record is None and meta is None:
            raise ValueError(
                say(
                    f"{name} 还没切好片段，没法接着做。重新加这一集",
                    f"{name} has no clips yet, so it cannot be continued. Add it again",
                )
            )
        if record is None:
            assert meta is not None
            # Text subtitles not attached yet are noted in episode.json, and avoc add picks them
            # up by itself.
            video, subtitles = Path(meta["video"]), Path(meta["subtitles"])
            return self.start(video, subtitles, offset=meta.get("subtitle_offset"), name=name)

        def path(key: str) -> Path | None:
            return Path(record[key]) if record.get(key) else None

        return self.start(
            Path(record["video"]),
            Path(record["subtitles"]),
            path("text_subtitles"),
            # Once the clips are cut the offset is known, so no token is needed to measure it.
            meta.get("subtitle_offset") if meta else record.get("offset"),
            name,
            record.get("styles"),
            record.get("spoken"),
            path("display_subtitles"),
        )

    def forget(self, name: str) -> None:
        """Give up an episode whose clips were never cut: delete its record and any half-built
        folder. An episode with clips is kept; deleting it is a separate matter."""
        from avoc.project import validate_name

        validate_name(name)
        with self.lock:
            if self.state == "running" and self.episode == name:
                raise ValueError(
                    say(f"{name} 正在加，先停下", f"{name} is being added. Stop it first")
                )
        if self._cut(name):
            raise ValueError(
                say(
                    f"{name} 已经切好了片段，这里不删",
                    f"{name} already has its clips, so it is not deleted here",
                )
            )
        folder = self._folder(name)
        if folder.is_dir() and not _remove(folder):
            raise ValueError(
                say(
                    f"删不掉 {name} 做了一半的文件，可能还在用。等一会儿再试",
                    f"Cannot delete the half-built files of {name}; they may still be in use. "
                    "Try again in a moment",
                )
            )
        self.drop_records({name})
