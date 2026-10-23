"""标注界面的后端：标签记录、台词文字、重训和接口。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from avs.app.labels import LabelStore
from avs.app.model import train_and_predict
from avs.app.server import AppState, create_app
from avs.app.workspace import Clip, neighbor_gap, text_for
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


def test_a_role_can_start_without_a_name_and_keeps_its_pattern(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}])
    first = store.new_role()
    second = store.new_role()
    assert (first, second) == ("角色 1", "角色 2")
    assert [r["named"] for r in store.roles] == [True, False, False]
    patterns = [r["pattern"] for r in store.roles]
    assert patterns == [0, 1, 2]

    store.apply([{"clip": "b", "label": first}])
    store.rename_role(first, "麦昆")
    renamed = store.role("麦昆")
    assert renamed is not None and renamed["named"] is True and renamed["pattern"] == 1

    # 合并掉的角色，它的图案编号不会被下一个新角色接着用。
    store.rename_role("麦昆", "A")
    assert store.role(store.new_role())["pattern"] == 3  # type: ignore[index]


def test_an_old_cast_without_patterns_gets_them_in_order(tmp_path: Path) -> None:
    folder = tmp_path / "labels"
    folder.mkdir()
    (folder / "cast.json").write_text(
        '{"schema": "avs.cast.v1", "roles": [{"name": "A", "color": "#000", "trainable": true,'
        ' "avatar": null}, {"name": "B", "color": "#111", "trainable": true, "avatar": null}]}',
        encoding="utf-8",
    )
    store = LabelStore(folder)
    assert [(r["named"], r["pattern"]) for r in store.roles] == [(True, 0), (True, 1)]


def test_text_is_found_by_overlap_not_exact_time() -> None:
    lines = [(1.0, 3.0, "你好"), (1.0, 3.0, "こんにちは"), (5.0, 6.0, "再见")]
    starts = [line[0] for line in lines]
    assert text_for(lines, starts, 1.2, 2.9) == "你好 / こんにちは"
    assert text_for(lines, starts, 4.0, 4.5) == ""
    assert text_for(lines, starts, 5.8, 7.0) == ""


def test_gap_ignores_the_clips_own_subtitle_lines() -> None:
    # 片段 1.2 到 2.9 是「你好」那行（双语两行）；下一句台词「再见」从 3.3 开始，没切出片段。
    lines = [(1.0, 3.0, "你好"), (1.0, 3.0, "こんにちは"), (3.3, 4.0, "再见")]
    starts = [line[0] for line in lines]
    spans = [(1.2, 2.9), (10.0, 10.5)]
    assert neighbor_gap(spans, 0, lines, starts) == pytest.approx(0.4)
    # 别的片段也算，重叠记成 0。
    assert neighbor_gap([(1.2, 2.9), (2.5, 3.5)], 0, [], []) == 0.0
    assert neighbor_gap([(1.2, 2.9)], 0, [], []) is None
    assert neighbor_gap([(1.2, 2.9), (30.0, 31.0)], 0, [], []) is None


def test_only_short_clips_far_from_other_lines_are_skipped() -> None:
    def clip(start: float, end: float, gap: float | None) -> Clip:
        return Clip("x", "ep1", start, end, "", 0, None, gap)

    assert clip(0.0, 0.8, 0.9).skipped
    assert clip(0.0, 0.8, None).skipped
    assert not clip(0.0, 0.8, 0.5).skipped
    assert not clip(0.0, 1.0, 5.0).skipped


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

    fresh = client.post("/api/label", json={"clips": [clips[2]["id"]], "new_role": True}).json()
    assert fresh["role"] == "角色 1"
    listed = {r["name"]: r for r in fresh["state"]["roles"]}
    assert listed["角色 1"]["named"] is False and listed["A"]["named"] is True

    png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
        "hQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    saved = client.post("/api/roles/avatar", json={"name": "角色 1", "image": png}).json()
    avatar = next(r["avatar"] for r in saved["roles"] if r["name"] == "角色 1")
    assert client.get(f"/media/avatar/{avatar}").status_code == 200


def test_skipped_clips_stay_out_of_the_work_lists_until_someone_labels_them(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    # 测试集里的片段 0.9 秒、彼此只隔 0.1 秒，都要人标。把最后一条挪成孤零零的。
    assert not any(c.skipped for c in state.workspace.clips)
    lonely = replace(state.workspace.clips[-1], gap=2.0)
    state.workspace.clips[-1] = lonely
    state.workspace.by_id[lonely.id] = lonely
    client = TestClient(create_app(state))

    client.post("/api/label", json={"clips": [state.workspace.clips[0].id], "label": "A"})
    client.post("/api/label", json={"clips": [state.workspace.clips[3].id], "label": "B"})
    clips = {c["id"]: c for c in client.get("/api/clips", params={"episode": "ep1"}).json()}
    assert clips[lonely.id]["status"] == "skipped"
    assert clips[lonely.id]["gap"] == 2.0
    assert lonely.id not in {c["id"] for c in client.get("/api/clips", params={"role": "B"}).json()}
    grouped = {c["id"] for g in client.get("/api/groups").json() for c in g["clips"]}
    assert lonely.id not in grouped
    assert client.get("/api/state").json()["episodes"][0]["counts"]["skipped"] == 1

    client.post("/api/label", json={"clips": [lonely.id], "label": "B"})
    clips = {c["id"]: c for c in client.get("/api/clips", params={"episode": "ep1"}).json()}
    assert clips[lonely.id]["status"] == "confirmed"
