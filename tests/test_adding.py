"""Adding an episode from the interface: checks before starting, progress, and stopping.

A small script stands in for `avoc add`, so no audio is processed."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from avoc.app.adding import Adding, clean_path

FAKE_ADD = """
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
workspace, video, name = Path(args[1]), args[2], args[args.index("--name") + 1]
folder = workspace / "episodes" / name
folder.mkdir(parents=True, exist_ok=True)
print("Failed to load a library", flush=True)
print("\\x1fcutting", flush=True)
print(" 50%|#####     | 1/2 [00:01<00:01]", end="\\r", file=sys.stderr, flush=True)
if "slow" in video:
    time.sleep(60)
if "bad" in video and not Path(video).with_suffix(".fixed").exists():
    print("\x1b[33mError: no luck\x1b[0m", file=sys.stderr, flush=True)
    sys.exit(1)
meta = {"name": name, "video": str(Path(video).resolve()), "args": args}
(folder / "episode.json").write_text(json.dumps(meta))
print("\\x1fdone", flush=True)
"""


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("avoc.app.adding.shutil.which", lambda _: "found")
    (tmp_path / "fake_add.py").write_text(FAKE_ADD, encoding="utf-8")
    for name in ("good.mkv", "slow.mkv", "bad.mkv", "notes.ass"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "ep.ass").write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
    return tmp_path


def adding(files: Path, loaded: list[str]) -> Adding:
    job = Adding(files / "work", loaded.append)
    job.program = [sys.executable, str(files / "fake_add.py")]
    return job


def finished(job: Adding) -> dict:
    job.ended.wait(timeout=30)
    return job.status()


def test_a_finished_episode_is_loaded_and_named_in_order(files: Path) -> None:
    loaded: list[str] = []
    job = adding(files, loaded)
    started = job.start(files / "good.mkv", files / "ep.ass", offset=-0.95)
    assert (started["state"], started["episode"]) == ("running", "ep01")
    status = finished(job)
    assert status["state"] == "done"
    assert status["lines"] == ["cutting", "done"]
    assert status["bar"].startswith("50%|")
    # A library line on the same output is kept apart from the progress.
    assert status["errors"] == ["Failed to load a library"]
    assert loaded == ["ep01"]
    # Same video again: the same episode, so a rerun carries on instead of making ep02.
    assert job.start(files / "good.mkv", files / "ep.ass", offset=0)["episode"] == "ep01"
    finished(job)


def test_a_failed_run_keeps_its_output(files: Path) -> None:
    loaded: list[str] = []
    job = adding(files, loaded)
    job.start(files / "bad.mkv", files / "ep.ass", offset=0)
    status = finished(job)
    assert status["state"] == "failed"
    assert status["lines"] == ["cutting"]
    # Two outputs read side by side, so their order is not fixed.
    assert sorted(status["errors"]) == ["Error: no luck", "Failed to load a library"]
    assert loaded == []


def test_stopping_before_clips_are_cut_removes_the_folder(files: Path) -> None:
    job = adding(files, [])
    job.start(files / "slow.mkv", files / "ep.ass", offset=0)
    folder = files / "work" / "episodes" / "ep01"
    for _ in range(100):
        if job.status()["lines"]:
            break
        time.sleep(0.1)
    with pytest.raises(ValueError, match="still being added"):
        job.start(files / "good.mkv", files / "ep.ass", offset=0)
    assert job.stop()["state"] == "stopped"
    assert not folder.exists()


def test_an_episode_never_cut_is_still_listed_after_a_restart(files: Path) -> None:
    # The fake leaves its folder behind when it fails, like a run cut off before it cleaned up.
    first = adding(files, [])
    first.start(files / "bad.mkv", files / "ep.ass", offset=0, display_subtitles=files / "ep.ass")
    assert finished(first)["state"] == "failed"
    folder = files / "work" / "episodes" / "ep01"
    (folder / "left.wav").write_text("x", encoding="utf-8")

    job = adding(files, loaded := [])  # A new server: nothing in memory.
    assert job.status()["state"] == "idle"
    assert job.not_cut() == ["ep01"]
    (files / "bad.fixed").write_text("x", encoding="utf-8")
    assert job.carry_on("ep01")["episode"] == "ep01"
    assert finished(job)["state"] == "done"
    assert not (folder / "left.wav").exists()
    meta = json.loads((folder / "episode.json").read_text())
    # The files it was first started with, not only those episode.json knows.
    assert meta["args"][meta["args"].index("--display-subs") + 1] == str(files / "ep.ass")
    assert loaded == ["ep01"]
    assert job.not_cut() == []
    assert not (files / "work" / "adding.json").exists()


def test_an_episode_never_cut_can_be_given_up(files: Path) -> None:
    job = adding(files, [])
    job.start(files / "bad.mkv", files / "ep.ass", offset=0)
    assert finished(job)["state"] == "failed"
    assert job.status()["cut"] is False
    folder = files / "work" / "episodes" / "ep01"
    assert job.not_cut() == ["ep01"] and folder.is_dir()
    job.forget("ep01")
    assert job.not_cut() == [] and not folder.exists()

    job.start(files / "good.mkv", files / "ep.ass", offset=0)
    assert finished(job)["cut"] is True
    with pytest.raises(ValueError, match="already has its clips"):
        job.forget("ep01")


def test_add_stops_by_itself_when_the_server_goes(tmp_path: Path) -> None:
    """The server holds the command's input open; when the server ends, the input closes."""
    import subprocess

    script = tmp_path / "child.py"
    script.write_text(
        "import sys, time\n"
        "from avoc.app.adding import stop_with_interface\n"
        "stop_with_interface()\n"
        "print('ready', flush=True)\n"
        "try:\n"
        "    for _ in range(600):\n"
        "        time.sleep(0.1)\n"
        "except KeyboardInterrupt:\n"
        "    print('cleaned up', flush=True)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stdin is not None
    assert child.stdout.readline().strip() == "ready"
    child.stdin.close()
    assert child.wait(timeout=20) == 0
    assert child.stdout.read().strip() == "cleaned up"


def test_bad_input_is_refused_before_starting(files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = adding(files, [])
    with pytest.raises(ValueError, match="cannot find the video"):
        job.start(files / "missing.mkv", files / "ep.ass", offset=0)
    with pytest.raises(ValueError, match="cannot find the text subtitles"):
        job.start(files / "good.mkv", files / "ep.ass", files / "missing.srt", offset=0)
    with pytest.raises(ValueError, match="cannot read this subtitle file"):
        job.start(files / "good.mkv", files / "notes.ass", offset=0)
    monkeypatch.setattr("avoc.pipeline.has_hf_token", lambda: False)
    with pytest.raises(ValueError, match="no Hugging Face token"):
        job.start(files / "good.mkv", files / "ep.ass")
    assert job.status()["state"] == "idle"


def test_chosen_styles_are_passed_on_and_checked(files: Path) -> None:
    job = adding(files, [])
    with pytest.raises(ValueError, match="no style Dial"):
        job.start(files / "good.mkv", files / "ep.ass", offset=0, styles=["Dial"])
    job.start(files / "good.mkv", files / "ep.ass", offset=0, styles=["Default"])
    assert finished(job)["state"] == "done"
    meta = json.loads((files / "work" / "episodes" / "ep01" / "episode.json").read_text())
    assert meta["args"][-2:] == ["--styles", "Default"]


def test_pasted_paths_lose_their_quotes() -> None:
    assert clean_path(' "D:/a b/ep 01.mkv" ') == Path("D:/a b/ep 01.mkv")
