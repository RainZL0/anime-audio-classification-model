"""The "Browse…" button: where the file window opens, and what the server sends back. The window
itself is swapped for a small script, so no window opens during tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from avoc.app import picker
from avoc.app.picker import start_folder
from avoc.app.server import AppState, create_app
from tests.fixtures import episode

FAKE_WINDOW = """
import json, sys
mode, spec = sys.argv[1], json.loads(sys.argv[2])
if mode == "pick":
    assert spec["types"][0][1].startswith("*.mkv"), spec
print(json.dumps({"path": spec["start"] + "/Episode 01.mkv" if mode == "pick" else None}))
"""


def test_window_opens_in_the_folder_of_the_box_or_where_avoc_started(tmp_path: Path) -> None:
    launched = tmp_path / "launched"
    video = tmp_path / "anime" / "Episode 01.mkv"
    video.parent.mkdir()
    assert start_folder("", launched) == launched
    assert start_folder(f'"{video}"', launched) == video.parent
    assert start_folder(str(video.parent), launched) == video.parent
    # The default export folder is made only by the first export: open in the nearest that exists.
    assert start_folder(str(tmp_path / "exports" / "2026-10-24"), launched) == tmp_path
    assert start_folder(str(Path(tmp_path.anchor) / "no-such-folder" / "x"), launched) == launched
    assert start_folder("gone/x.mkv", launched) == launched


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    root = tmp_path / "ws"
    (root / "episodes").mkdir(parents=True)
    episode(root / "episodes", "ep1", np.eye(6)[:, :3] + 0.1)
    return TestClient(create_app(AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")))


def _swap_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str) -> None:
    script = tmp_path / "window.py"
    script.write_text(FAKE_WINDOW, encoding="utf-8")
    monkeypatch.setattr(picker, "PROGRAM", [sys.executable, str(script), mode])


def test_browse_sends_back_the_picked_path_or_nothing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "anime"
    folder.mkdir()
    _swap_window(monkeypatch, tmp_path, "pick")
    picked = client.post("/api/pick", json={"kind": "video", "current": str(folder / "old.mkv")})
    assert Path(picked.json()["path"]) == folder / "Episode 01.mkv"

    _swap_window(monkeypatch, tmp_path, "cancel")
    assert client.post("/api/pick", json={"kind": "folder"}).json() == {"path": None}


def test_browse_says_what_to_do_when_the_window_cannot_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(picker, "PROGRAM", [sys.executable, "-c", "raise SystemExit('no tkinter')"])
    failed = client.post("/api/pick", json={"kind": "subtitles"}, headers={"x-language": "en"})
    assert failed.status_code == 400 and "paste the path" in failed.json()["detail"]
    assert client.post("/api/pick", json={"kind": "music"}).status_code == 400
