"""Adding an episode from the interface: checks before starting, progress, and stopping.

A small script stands in for `avs add`, so no audio is processed."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from avs.app.adding import Adding, clean_path

FAKE_ADD = """
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
workspace, video, name = Path(args[1]), args[2], args[args.index("--name") + 1]
folder = workspace / "episodes" / name
folder.mkdir(parents=True, exist_ok=True)
print("cutting", flush=True)
print(" 50%|#####     | 1/2 [00:01<00:01]", end="\\r", file=sys.stderr, flush=True)
if "slow" in video:
    time.sleep(60)
if "bad" in video:
    print("\x1b[33mError: no luck\x1b[0m", file=sys.stderr, flush=True)
    sys.exit(1)
meta = {"name": name, "video": str(Path(video).resolve())}
(folder / "episode.json").write_text(json.dumps(meta))
print("done", flush=True)
"""


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("avs.app.adding.shutil.which", lambda _: "found")
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
    assert status["bar"].startswith("50%|") and status["errors"] == []
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
    assert status["errors"] == ["Error: no luck"]
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


def test_bad_input_is_refused_before_starting(files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = adding(files, [])
    with pytest.raises(ValueError, match="cannot find the video"):
        job.start(files / "missing.mkv", files / "ep.ass", offset=0)
    with pytest.raises(ValueError, match="cannot find the text subtitles"):
        job.start(files / "good.mkv", files / "ep.ass", files / "missing.srt", offset=0)
    with pytest.raises(ValueError, match="cannot read this subtitle file"):
        job.start(files / "good.mkv", files / "notes.ass", offset=0)
    monkeypatch.setattr("avs.pipeline.has_hf_token", lambda: False)
    with pytest.raises(ValueError, match="no Hugging Face token"):
        job.start(files / "good.mkv", files / "ep.ass")
    assert job.status()["state"] == "idle"


def test_pasted_paths_lose_their_quotes() -> None:
    assert clean_path(' "D:/a b/ep 01.mkv" ') == Path("D:/a b/ep 01.mkv")
