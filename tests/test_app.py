"""标注界面的后端：标签记录、台词文字、重训和接口。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from avs.app.labels import LabelStore
from avs.app.model import train_and_predict
from avs.app.server import AppState, create_app
from avs.app.workspace import text_for
from tests.test_drift import episode


def test_store_keeps_every_step_and_undoes_whole_batches(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}, {"clip": "b", "label": "A"}], source="import:x")
    assert not store.can_undo()
    store.apply([{"clip": "a", "label": "B"}, {"clip": "c", "reject": "A", "on": True}])
    assert store.labels == {"a": "B", "b": "A"}
    assert store.rejects["c"] == {"A"}
    assert store.apply([{"clip": "a", "label": "B"}]) is None
    store.undo()
    assert store.labels == {"a": "A", "b": "A"}
    assert store.rejects["c"] == set()
    assert not store.can_undo()

    again = LabelStore(tmp_path / "labels")
    assert again.labels == store.labels
    assert [r["name"] for r in again.roles] == ["A", "B"]


def test_rename_into_an_existing_role_merges_them(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "红毛"}, {"clip": "b", "label": "Nice Nature"}])
    store.rename_role("红毛", "Nice Nature")
    assert set(store.labels.values()) == {"Nice Nature"}
    assert [r["name"] for r in LabelStore(tmp_path / "labels").roles] == ["Nice Nature"]
    with pytest.raises(ValueError, match="特殊标签"):
        store.rename_role("Nice Nature", "__unclear__")


def test_text_is_found_by_overlap_not_exact_time() -> None:
    lines = [(1.0, 3.0, "你好"), (1.0, 3.0, "こんにちは"), (5.0, 6.0, "再见")]
    starts = [line[0] for line in lines]
    assert text_for(lines, starts, 1.2, 2.9) == "你好 / こんにちは"
    assert text_for(lines, starts, 4.0, 4.5) == ""
    assert text_for(lines, starts, 5.8, 7.0) == ""


def test_a_voice_unlike_any_known_role_is_not_trusted() -> None:
    rng = np.random.default_rng(0)
    centers = np.eye(3)
    rows = [centers[i % 2] + rng.normal(0, 0.05, 3) for i in range(40)]
    features = np.array([*rows, centers[2] + rng.normal(0, 0.05, 3)])
    features /= np.linalg.norm(features, axis=1, keepdims=True)
    names = ["A" if i % 2 == 0 else "B" for i in range(40)]

    few = train_and_predict(features, list(range(4)), names[:4], {})
    assert few.threshold is None
    assert few.guesses[40].familiar is None

    trained = train_and_predict(features, list(range(40)), names, {})
    assert trained.threshold is not None
    assert trained.guesses[39].familiar is True
    assert trained.guesses[40].familiar is False


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "episodes").mkdir(parents=True)
    a, b = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    episode(root / "episodes", "ep1", np.array([a, a, a, b, b, b], dtype=float))
    return root


def test_api_labels_retrains_and_undoes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clips = client.get("/api/clips", params={"episode": "ep1"}).json()
    assert len(clips) == 6
    assert all(c["status"] == "unlabeled" for c in clips)

    groups = client.get("/api/groups", params={"episode": "ep1"}).json()
    assert sorted(g["size"] for g in groups) == [3, 3]

    result = client.post("/api/label", json={"clips": [clips[0]["id"]], "label": "A"}).json()
    result = client.post("/api/label", json={"clips": [clips[3]["id"]], "label": "B"}).json()
    assert result["ripple"] > 0
    after = {c["id"]: c for c in client.get("/api/clips", params={"episode": "ep1"}).json()}
    assert after[clips[1]["id"]]["guess"][0]["name"] == "A"
    assert after[clips[4]["id"]]["guess"][0]["name"] == "B"
    assert after[clips[0]["id"]]["status"] == "confirmed"

    rejected = client.post(
        "/api/changes", json={"changes": [{"clip": clips[1]["id"], "reject": "A", "on": True}]}
    ).json()
    moved = {c["id"]: c for c in rejected["updated"]}
    assert moved[clips[1]["id"]]["guess"][0]["name"] == "B"

    undone = client.post("/api/undo").json()
    assert undone["undo"] is True
    state_now = client.get("/api/state").json()
    assert {r["name"] for r in state_now["roles"]} == {"A", "B"}
    assert client.post("/api/label", json={"clips": ["nope"], "label": "A"}).status_code == 400
