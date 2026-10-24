"""Backend of the labeling interface: label records, dialogue text, retraining, and the API."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from avoc.app.labels import OTHER, LabelStore
from avoc.app.model import train_and_predict
from avoc.app.server import AppState, create_app
from avoc.app.workspace import Clip, neighbor_gap, text_for
from tests.fixtures import episode


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
    # B was created by the batch that was undone. After the undo it has no clips,
    # so it is removed too.
    assert [r["name"] for r in again.roles] == ["A"]


def test_rename_into_an_existing_role_merges_them(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "红毛"}, {"clip": "b", "label": "Nice Nature"}])
    store.rename_role("红毛", "Nice Nature")
    assert set(store.labels.values()) == {"Nice Nature"}
    assert [r["name"] for r in LabelStore(tmp_path / "labels").roles] == ["Nice Nature"]
    with pytest.raises(ValueError, match="cannot be empty"):
        store.rename_role("Nice Nature", "__unclear__")


def test_renaming_a_role_with_no_clips_can_be_undone(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}])
    store.apply([{"clip": "a", "label": "B"}])
    assert store.rename_role("A", "C") is not None
    store.undo()
    assert {r["name"] for r in store.roles} == {"A", "B"}
    assert store.labels == {"a": "B"}


def test_retired_labels_count_as_unlabeled(tmp_path: Path) -> None:
    """A retired old label (such as an unsure one) counts as no label when replayed, imported, or
    undone. Undo also does not get stuck."""
    folder = tmp_path / "labels"
    folder.mkdir()
    lines = [
        {"batch": 1, "time": "t", "source": "human", "undo_of": None,
         "changes": [{"clip": "b", "before": None, "after": "teo"}]},
        {"batch": 2, "time": "t", "source": "human", "undo_of": None,
         "changes": [{"clip": "a", "before": None, "after": "__multiple__"}]},
    ]  # fmt: skip
    (folder / "events.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    store = LabelStore(folder)
    assert store.labels == {"b": "teo"}
    assert [r["name"] for r in store.roles] == ["teo"]
    assert store.apply([{"clip": "c", "label": "__unclear__"}]) is None
    # Undoing the batch that only touched retired labels: no real change, but it is still recorded
    # as undone, so earlier batches can be undone next.
    store.undo()
    assert store.labels == {"b": "teo"}
    store.undo()
    assert store.labels == {}


def test_a_role_can_start_without_a_name_and_keeps_its_pattern(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}])
    first = store.new_role()
    second = store.new_role()
    assert (first, second) == ("Character 1", "Character 2")
    assert [r["named"] for r in store.roles] == [True, False, False]
    patterns = [r["pattern"] for r in store.roles]
    assert patterns == [0, 1, 2]

    store.apply([{"clip": "b", "label": first}])
    store.rename_role(first, "麦昆")
    renamed = store.role("麦昆")
    assert renamed is not None and renamed["named"] is True and renamed["pattern"] == 1

    # A character that was merged away does not have its pattern number reused by the next new one.
    store.rename_role("麦昆", "A")
    assert store.role(store.new_role())["pattern"] == 3  # type: ignore[index]


def test_undo_puts_the_role_list_back_too(tmp_path: Path) -> None:
    """When undoing a batch, the characters that batch also created, renamed, or merged are changed
    back too, so no empty character is left."""
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}])
    store.update_role("A", target=False)

    # A character created by typing a new name is also removed once undo leaves it with no clips.
    store.apply([{"clip": "b", "label": "B"}])
    store.undo()
    assert [r["name"] for r in store.roles] == ["A"]

    # The same goes for an unnamed character made with the N key.
    fresh = store.new_role()
    store.apply([{"clip": "b", "label": fresh}], cast={"unnamed": [fresh]})
    store.rename_role(fresh, "麦昆")
    store.undo()
    role = store.role(fresh)
    assert role is not None and role["named"] is False and store.role("麦昆") is None
    assert store.labels["b"] == fresh
    store.undo()
    assert [r["name"] for r in store.roles] == ["A"]

    # After undoing a merge, the character that was merged away comes back unchanged. The one that
    # was kept also gets its original target status back.
    store.apply([{"clip": "c", "label": "C"}])
    store.rename_role("C", "A")
    assert store.role("A")["target"] is True  # type: ignore[index]
    store.undo()
    assert [r["name"] for r in store.roles] == ["A", "C"]
    assert store.role("A")["target"] is False  # type: ignore[index]
    assert store.labels == {"a": "A", "c": "C"}
    assert [r["name"] for r in LabelStore(tmp_path / "labels").roles] == ["A", "C"]


def test_an_old_cast_without_patterns_gets_them_in_order(tmp_path: Path) -> None:
    folder = tmp_path / "labels"
    folder.mkdir()
    (folder / "cast.json").write_text(
        '{"schema": "cast.v1", "roles": [{"name": "A", "color": "#000", "trainable": true,'
        ' "avatar": null}, {"name": "B", "color": "#111", "trainable": true, "avatar": null}]}',
        encoding="utf-8",
    )
    store = LabelStore(folder)
    assert [(r["named"], r["pattern"]) for r in store.roles] == [(True, 0), (True, 1)]
    assert store.targets() == ["A", "B"]


def test_other_remembers_the_targets_it_was_judged_against(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "label": "A"}])
    store.apply([{"clip": "o", "label": OTHER}])
    assert store.against["o"] == {"A"}

    store.apply([{"clip": "b", "label": "B"}])
    store.update_role("A", target=False)
    store.apply([{"clip": "o", "label": OTHER}])
    assert store.against["o"] == {"B"}
    store.undo()
    assert store.against["o"] == {"A"}
    assert LabelStore(tmp_path / "labels").against["o"] == {"A"}

    store.update_role("A", target=True)
    store.rename_role("A", "teo")
    assert store.against["o"] == {"teo"}


def test_text_is_found_by_overlap_not_exact_time() -> None:
    lines = [(1.0, 3.0, "你好"), (1.0, 3.0, "こんにちは"), (5.0, 6.0, "再见")]
    starts = [line[0] for line in lines]
    assert text_for(lines, starts, 1.2, 2.9) == "你好 / こんにちは"
    assert text_for(lines, starts, 4.0, 4.5) == ""
    assert text_for(lines, starts, 5.8, 7.0) == ""


def test_gap_ignores_the_clips_own_subtitle_lines() -> None:
    # Clip 1.2 to 2.9 is the "你好" line (two bilingual lines). The next line, "再见", starts at 3.3
    # and was not cut into a clip.
    lines = [(1.0, 3.0, "你好"), (1.0, 3.0, "こんにちは"), (3.3, 4.0, "再见")]
    starts = [line[0] for line in lines]
    spans = [(1.2, 2.9), (10.0, 10.5)]
    assert neighbor_gap(spans, 0, lines, starts) == pytest.approx(0.4)
    # Other clips count too, and an overlap is recorded as 0.
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

    def examples(n: int) -> dict[str, tuple[list[int], list[int]]]:
        even, odd = list(range(0, n, 2)), list(range(1, n, 2))
        return {"A": (even, odd), "B": (odd, even)}

    few = train_and_predict(features, examples(4), {})
    assert few.threshold is None
    assert few.guesses[40].familiar is None

    trained = train_and_predict(features, examples(40), {})
    assert trained.threshold is not None
    assert trained.guesses[39].names[0] == "B"
    assert trained.guesses[39].familiar is True
    assert trained.guesses[40].familiar is False


def test_other_only_counts_against_the_targets_of_its_time() -> None:
    # A and C have different voices. C's clips were labeled "other" while C was not yet a target.
    # C was made a target later, so those clips should not count as C's negative examples.
    rng = np.random.default_rng(1)
    centers = np.eye(3)
    features = np.array([centers[i // 10] + rng.normal(0, 0.05, 3) for i in range(30)])
    features /= np.linalg.norm(features, axis=1, keepdims=True)
    a, b, c = list(range(10)), list(range(10, 20)), list(range(20, 30))
    only_a = train_and_predict(features, {"A": (a, b + c)}, {})
    assert only_a.guesses[25].names[0] == "__other__"
    with_c = train_and_predict(features, {"A": (a, b + c), "C": (c[:2], a + b)}, {})
    assert with_c.guesses[25].names[0] == "C"


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "episodes").mkdir(parents=True)
    a, b = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    episode(root / "episodes", "ep1", np.array([a, a, a, b, b, b], dtype=float))
    return root


def test_an_episode_without_voiceprints_is_skipped_not_fatal(tmp_path: Path) -> None:
    import shutil

    root = _workspace(tmp_path)
    half = episode(root / "episodes", "ep2", np.array([[1.0, 0.0, 0.0]] * 6, dtype=float))
    shutil.rmtree(half / "embeddings")
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    summary = TestClient(create_app(state)).get("/api/state").json()
    assert [e["name"] for e in summary["episodes"]] == ["ep1"]
    assert "avoc add" in summary["skipped"]["ep2"]
    assert {c.episode for c in state.workspace.clips} == {"ep1"}


FINISH_VOICEPRINTS = """
import sys
from pathlib import Path
import numpy as np
from avoc.project import cache_signature, read_json, write_json
args = sys.argv[1:]
folder = Path(args[1]) / "episodes" / args[args.index("--name") + 1]
rows = read_json(folder / "segments.json")
cache = folder / "embeddings/redimnet2-b6"
cache.mkdir(parents=True)
np.save(cache / "vectors.npy", np.tile(np.float32([1, 0, 0]), (len(rows), 1)))
write_json(cache / "metadata.json", rows)
write_json(cache / "cache.json", cache_signature(folder, "redimnet2-b6"))
"""


def test_an_unfinished_episode_can_be_carried_on_from_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page's "carry on" button reruns avoc add with the files the episode recorded, and the
    workspace is reloaded once it is done. A small script stands in for avoc add."""
    import shutil
    import sys

    monkeypatch.setattr("avoc.app.adding.shutil.which", lambda _: "found")
    root = _workspace(tmp_path)
    half = episode(root / "episodes", "ep2", np.array([[1.0, 0.0, 0.0]] * 6, dtype=float))
    shutil.rmtree(half / "embeddings")
    (tmp_path / "ep2.mkv").write_text("x", encoding="utf-8")
    (tmp_path / "ep2.ass").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    meta = json.loads((half / "episode.json").read_text(encoding="utf-8"))
    meta.update(video=str(tmp_path / "ep2.mkv"), subtitles=str(tmp_path / "ep2.ass"))
    meta["subtitle_offset"] = -0.95
    (half / "episode.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "finish.py").write_text(FINISH_VOICEPRINTS, encoding="utf-8")

    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    state.adding.program = [sys.executable, str(tmp_path / "finish.py")]
    client = TestClient(create_app(state))
    english = {"X-Language": "en"}
    missing = client.post("/api/add", json={"video": "x.mkv"}, headers=english)
    assert missing.status_code == 400 and "subtitles" in missing.json()["detail"]
    assert client.post("/api/add", json={"resume": "ep2"}).json()["episode"] == "ep2"
    state.adding.ended.wait(timeout=60)
    assert client.get("/api/add").json()["state"] == "done", state.adding.lines
    summary = client.get("/api/state").json()
    assert [e["name"] for e in summary["episodes"]] == ["ep1", "ep2"]
    assert summary["skipped"] == {}


def test_an_episode_never_cut_is_listed_from_the_record_and_can_be_given_up(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    record = {"video": str(tmp_path / "x.mkv"), "subtitles": str(tmp_path / "x.ass")}
    (root / "adding.json").write_text(json.dumps({"ep9": record, "ep1": record}))
    client = TestClient(create_app(AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")))
    summary = client.get("/api/state", headers={"X-Language": "en"}).json()
    # ep1 loads in full, so its record is dropped.
    assert summary["not_cut"] == ["ep9"]
    assert "never cut" in summary["skipped"]["ep9"]
    after = client.post("/api/add/forget", json={"episode": "ep9"}).json()
    assert after["not_cut"] == [] and after["skipped"] == {}
    assert not (root / "adding.json").exists()


def test_messages_follow_the_page_language(tmp_path: Path) -> None:
    import shutil

    root = _workspace(tmp_path)
    half = episode(root / "episodes", "ep2", np.array([[1.0, 0.0, 0.0]] * 6, dtype=float))
    shutil.rmtree(half / "embeddings")
    client = TestClient(create_app(AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")))
    english = {"X-Language": "en"}
    assert "voiceprints" in client.get("/api/state", headers=english).json()["skipped"]["ep2"]
    assert "声纹" in client.get("/api/state").json()["skipped"]["ep2"]
    wrong = client.post("/api/label", json={"clips": ["nope"], "label": "A"}, headers=english)
    assert wrong.json()["detail"] == "no such clip"
    first = client.get("/api/clips").json()[0]["id"]
    named = client.post("/api/label", json={"clips": [first], "new_role": True}, headers=english)
    assert named.json()["role"] == "Character 1"


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
    assert moved[clips[1]["id"]]["guess"][0]["name"] != "A"

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


def test_groups_hold_only_lines_still_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clips = [c["id"] for c in client.get("/api/clips", params={"episode": "ep1"}).json()]
    client.post("/api/label", json={"clips": [clips[0]], "label": "A"})

    def grouped() -> set[str]:
        return {c["id"] for g in client.get("/api/groups").json() for c in g["clips"]}

    assert grouped() == set(clips[1:])
    # The test set is too small for the machine to be confident, so make one guess confident. Its
    # partner is then alone, and a group of one is not shown.
    status = state.status
    monkeypatch.setattr(state, "status", lambda c: "auto" if c.id == clips[1] else status(c))
    assert grouped() == set(clips[3:])


def test_skipped_clips_stay_out_of_the_work_lists_until_someone_labels_them(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    # The test set's clips are 0.9 seconds long and only 0.1 seconds apart, so all need a person to
    # label them. Move the last one so it stands alone.
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


def test_an_added_target_lists_old_others_that_may_be_it(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    ids = [c.id for c in state.workspace.clips]
    client.post("/api/label", json={"clips": [ids[0]], "label": "A"})
    client.post("/api/label", json={"clips": [ids[3]], "label": OTHER})
    summary = client.get("/api/state").json()
    assert summary["other"]["confirmed"] == 1
    listed = {c["id"]: c for c in client.get("/api/clips", params={"episode": "ep1"}).json()}
    assert {listed[i]["guess"][0]["name"] for i in (ids[4], ids[5])} == {OTHER}

    # Later B was made a target too. When ids[3] was labeled "other", B was not yet a target, so
    # ids[3] should appear in the "possibly missed" list.
    client.post("/api/label", json={"clips": [ids[4]], "label": "B"})
    listed = {c["id"]: c for c in client.get("/api/clips", params={"role": "B"}).json()}
    assert listed[ids[3]].get("maybe") is True
    assert ids[5] in listed and not listed[ids[5]].get("maybe")

    # Remove A as a target: A's labels stay, but the machine no longer guesses A.
    client.post("/api/roles", json={"name": "A", "target": False})
    guesses = {
        c["id"]: c["guess"] for c in client.get("/api/clips", params={"episode": "ep1"}).json()
    }
    assert all(g["name"] != "A" for g in guesses[ids[1]])
    assert state.store.labels[ids[0]] == "A"


def test_roles_report_total_length_and_other_can_be_listed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clips = state.workspace.clips
    client.post("/api/label", json={"clips": [clips[0].id], "label": "A", "unusable": True})
    client.post("/api/label", json={"clips": [clips[1].id], "label": "A"})
    client.post("/api/label", json={"clips": [clips[2].id, clips[3].id], "label": OTHER})
    summary = client.get("/api/state").json()
    a = next(r for r in summary["roles"] if r["name"] == "A")
    assert a["seconds"] == round(clips[0].duration + clips[1].duration, 1)
    assert a["low_seconds"] == round(clips[0].duration, 1)
    assert summary["other"]["seconds"] == round(clips[2].duration + clips[3].duration, 1)

    # "Other" can also be opened. Confirmed clips are sorted from the ones closest to a target
    # character, and there is no "possibly missed" list.
    listed = client.get("/api/clips", params={"role": OTHER}).json()
    assert not any(c.get("maybe") for c in listed)
    mine = [c for c in listed if c["label"] == OTHER]
    assert {c["id"] for c in mine} == {clips[2].id, clips[3].id}
    best = [max(g["p"] for g in c["guess"] if g["name"] != OTHER) for c in mine]
    assert best == sorted(best, reverse=True)


def test_unusable_keeps_the_name_but_stays_out_of_training_and_export(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "labels")
    store.apply([{"clip": "a", "unusable": True}])
    assert store.unusable == {"a"}
    assert store.apply([{"clip": "a", "unusable": True}]) is None
    store.undo()
    assert store.unusable == set()
    store.apply([{"clip": "a", "unusable": True}])
    assert LabelStore(tmp_path / "labels").unusable == {"a"}

    import soundfile as sf

    root = _workspace(tmp_path)
    # Export must cut from the vocals track at its original sample rate. The test set's own file is
    # 16 kHz and 1 second long, so use a longer one.
    sf.write(root / "episodes/ep1/ep1.wav", np.zeros(44100 * 10), 44100)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    first, second = (c.id for c in state.workspace.clips[:2])
    client.post("/api/label", json={"clips": [first, second], "label": "A"})
    assert state.trained["labels"] == 2
    marked = client.post("/api/changes", json={"changes": [{"clip": first, "unusable": True}]})
    view = marked.json()["updated"][0]
    assert view["unusable"] is True and view["label"] == "A"
    assert state.trained["labels"] == 1

    body = {"roles": ["A"], "form": "folder"}
    part = client.post("/api/export", json={**body, "out": str(tmp_path / "part")}).json()
    assert part["files"] == 1 and part["rejected"] == {"人标了质量低": 1}
    assert "人标了质量低" in (tmp_path / "part" / "rejected.tsv").read_text("utf-8")

    client.post("/api/changes", json={"changes": [{"clip": second, "unusable": True}]})
    none = client.post("/api/export", json={**body, "out": str(tmp_path / "none")})
    assert none.status_code == 400 and "2 条都标了质量低" in none.json()["detail"]


def test_default_export_folder_moves_on_once_used(tmp_path: Path) -> None:
    from avoc.app.server import free_export_folder

    first = free_export_folder(tmp_path)
    assert first.parent == tmp_path.resolve() / "exports"
    first.mkdir(parents=True)
    assert free_export_folder(tmp_path) == first, "an empty folder can still take an export"
    (first / "train.list").write_text("", encoding="utf-8")
    assert free_export_folder(tmp_path).name == f"{first.name}-2"


def test_one_choice_sets_who_and_quality_together(tmp_path: Path) -> None:
    """One choice: labeling "target, low quality" sets both at once. Changing it to clean target,
    to "other", or clearing it also turns "low quality" off."""
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clip = state.workspace.clips[0].id

    def label(name: str | None, unusable: bool = False) -> dict:
        body = {"clips": [clip], "label": name, "unusable": unusable}
        return client.post("/api/label", json=body).json()["updated"][0]

    view = label("A", unusable=True)
    assert view["label"] == "A" and view["unusable"] is True
    assert label("A")["unusable"] is False
    label("A", unusable=True)
    assert label(OTHER, unusable=True)["unusable"] is False
    label("A", unusable=True)
    assert label(None)["unusable"] is False
    client.post("/api/undo")
    assert state.store.labels[clip] == "A" and state.store.unusable == {clip}

    # A name of only spaces counts as clearing the label, and it must not leave
    # "low quality" behind.
    assert label("  ", unusable=True)["unusable"] is False
    assert clip not in state.store.labels


def test_changes_api_rejects_unknown_entries_and_reads_old_flag_names(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clip = state.workspace.clips[0].id
    client.post("/api/label", json={"clips": [clip], "label": "A"})
    # The old "multiple people" switch name is still recognized as "low quality", and is not taken
    # as clearing the label.
    client.post("/api/changes", json={"changes": [{"clip": clip, "overlap": True}]})
    assert state.store.labels[clip] == "A" and state.store.unusable == {clip}
    bad = client.post("/api/changes", json={"changes": [{"clip": clip}]})
    assert bad.status_code == 400
    assert state.store.labels[clip] == "A"


def test_page_files_are_checked_on_every_load(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    client = TestClient(create_app(AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")))
    for path in ("/", "/static/assets/index.js", "/static/assets/index.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_prefetch_cuts_nearby_and_later_clips_in_the_background(tmp_path: Path) -> None:
    import time

    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    first = state.workspace.clips[0]
    near = [
        c for c in state.workspace.clips
        if c.episode == first.episode and (c.start >= first.start or c.end >= first.start - 60)
    ]  # fmt: skip
    episode = state.workspace.episodes[first.episode]
    assert not episode.get("video")
    queued = client.post("/api/prefetch", json={"clip": first.id}).json()["queued"]
    assert queued == len(near)
    folder = Path(episode["directory"]) / "app_media" / "audio"
    deadline = time.time() + 30
    while time.time() < deadline and not all((folder / f"{c.id}.wav").exists() for c in near):
        time.sleep(0.1)
    assert state.prefetch(first.id) == 0
    assert client.post("/api/prefetch", json={"clip": "nope"}).status_code == 404


def test_longer_context_is_cut_separately_on_request(tmp_path: Path) -> None:
    import soundfile as sf

    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clip = state.workspace.clips[0]
    plain = client.get(f"/media/audio/{clip.id}.wav")
    wide = client.get(f"/media/audio/{clip.id}.wav?context=5")
    assert plain.status_code == wide.status_code == 200
    plain_path, wide_path = state.media("audio", clip.id), state.media("audio", clip.id, 5)
    assert plain_path != wide_path
    total = sf.info(str(state.workspace.episodes[clip.episode]["vocals"])).duration
    expected = min(clip.end + 5, total) - max(0, clip.start - 5)
    assert sf.info(str(wide_path)).duration == pytest.approx(expected, abs=0.01)
    assert client.get(f"/media/audio/{clip.id}.wav?context=7").status_code == 404


def test_old_overlap_records_count_as_unusable(tmp_path: Path) -> None:
    """The old separate "multiple people" switch was merged into "low quality". Old records, when
    replayed or undone, count as "low quality"."""
    folder = tmp_path / "labels"
    folder.mkdir()
    old = {
        "batch": 1, "time": "2026-01-01T00:00:00+00:00", "source": "human", "undo_of": None,
        "changes": [{"clip": "a", "overlap": True, "before": False, "after": True}],
    }  # fmt: skip
    (folder / "events.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
    store = LabelStore(folder)
    assert store.unusable == {"a"}
    assert store.apply([{"clip": "a", "unusable": True}]) is None
    store.undo()
    assert store.unusable == set()
    assert LabelStore(folder).unusable == set()


def test_audio_cut_does_not_share_its_unfinished_file_with_another_app(tmp_path: Path) -> None:
    import soundfile as sf

    from avoc.app.server import _cut_audio

    vocals = tmp_path / "vocals.wav"
    sf.write(str(vocals), np.zeros(16000, dtype=np.float32), 16000)
    target = tmp_path / "cut.wav"
    # An unfinished file left by another app open on the same project.
    other = target.with_suffix(".1.part.wav")
    other.write_bytes(b"half")
    _cut_audio(vocals, 0.25, 0.75, target)
    assert sf.info(str(target)).frames == 8000
    assert other.read_bytes() == b"half"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cut.1.part.wav", "cut.wav", "vocals.wav"]


def test_a_broken_cut_is_cut_again_on_request(tmp_path: Path) -> None:
    import soundfile as sf

    state = AppState(_workspace(tmp_path), ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    clip = state.workspace.clips[0]
    path = state.media("audio", clip.id)
    path.write_bytes(b"broken")
    assert client.get(f"/media/audio/{clip.id}.wav").content == b"broken"
    assert client.get(f"/media/audio/{clip.id}.wav?fresh=1").status_code == 200
    assert sf.info(str(path)).duration == pytest.approx(clip.end - clip.start, abs=0.01)
