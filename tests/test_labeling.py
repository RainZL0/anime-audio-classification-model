"""标注计划：只安排候选改动过、且人工归档还没覆盖的短片段。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from avs.labeling import (
    _roster_archives,
    build_plan,
    build_sample,
    known_names,
    reference_clips,
)
from avs.project import read_json, segment_rows, write_json

# 0.5 秒的算短片段，2 秒的算长片段；分界取自 avs.stages.cluster.SHORT_SECONDS。
SPANS = [
    {"start": 0, "end": 2},
    {"start": 3, "end": 3.5},
    {"start": 4, "end": 4.5},
    {"start": 5, "end": 5.5},
    {"start": 6, "end": 6.5},
]


def make_episode(root: Path, name: str) -> tuple[Path, list[dict[str, Any]]]:
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    vocals.write_bytes(b"fixture")
    write_json(
        directory / "episode.json",
        {
            "schema": "avs.episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(directory / "analysis.wav"),
            "source": str(vocals),
            "sample_rate": 44100,
        },
    )
    rows = segment_rows(name, SPANS)
    write_json(directory / "segments.json", rows)
    return directory, rows


def make_groups(path: Path, directory: Path, rows: list[dict[str, Any]], groups: list[str]) -> None:
    episode = read_json(directory / "episode.json")
    write_json(
        path,
        {
            "schema": "avs.groups.v1",
            "episodes": {episode["name"]: episode},
            "assignments": [
                dict(row, speaker=group) for row, group in zip(rows, groups, strict=True)
            ],
        },
    )


def test_plan_takes_only_short_clips_the_candidate_attached_and_not_yet_labelled(
    tmp_path: Path,
) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    # 候选把 3 条短片段挂进 speaker_001，第 5 条留在只有自己的组里。
    make_groups(
        candidate,
        directory,
        rows,
        ["speaker_001", "speaker_001", "speaker_001", "speaker_001", "speaker_002"],
    )
    # 基线只认下第 2 条；第 3、4 条在两套分组里归属不同。
    make_groups(
        baseline,
        directory,
        rows,
        ["speaker_001", "speaker_001", "speaker_003", "speaker_004", "speaker_002"],
    )
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {"source": f"{directory / 'ep1.wav'}", "clips": [dict(rows[1], name="A")]},
    )

    plan = build_plan(candidate, baseline, [annotation], tmp_path / "plan.json")
    entries = plan["episodes"]["ep1"]
    # 长片段（第 1 条）、已标过的（第 2 条）、独自成组的（第 5 条）都不该出现。
    assert [e["clip_id"] for e in entries] == [rows[2]["id"], rows[3]["id"]]
    assert [e["reason"] for e in entries] == ["moved", "moved"]
    assert plan["summary"]["ep1"] == {"clips": 2, "moved": 2, "seconds": 1.0}
    assert read_json(tmp_path / "plan.json") == plan


def test_plan_marks_clips_both_rules_agree_on_and_refuses_to_overwrite(tmp_path: Path) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    groups = ["speaker_001"] * 5
    make_groups(candidate, directory, rows, groups)
    make_groups(baseline, directory, rows, groups)
    out = tmp_path / "plan.json"

    plan = build_plan(candidate, baseline, [], out)
    assert [e["reason"] for e in plan["episodes"]["ep1"]] == ["kept"] * 4
    with pytest.raises(ValueError, match="已存在"):
        build_plan(candidate, baseline, [], out)


def test_plan_refuses_two_groupings_over_different_clips(tmp_path: Path) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    make_groups(candidate, directory, rows, ["speaker_001"] * 5)
    make_groups(baseline, directory, rows[:4], ["speaker_001"] * 4)
    with pytest.raises(ValueError, match="片段不一致"):
        build_plan(candidate, baseline, [], tmp_path / "plan.json")


def test_sample_from_plan_takes_exactly_the_planned_clips_in_time_order(tmp_path: Path) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    make_groups(candidate, directory, rows, ["speaker_001"] * 5)
    make_groups(baseline, directory, rows, ["speaker_002"] * 5)
    out = tmp_path / "plan.json"
    build_plan(candidate, baseline, [], out)

    archive = tmp_path / "ep1-short.json"
    data = build_sample(directory, archive, count=1, plan=out)
    assert [c["clip_id"] for c in data["clips"]] == [row["id"] for row in rows[1:]]
    assert all(c["name"] is None for c in data["clips"])
    assert data["plan"] == str(out.resolve())
    assert "seed" not in data
    # 归档已存在就原样返回，计划不会再覆盖已经标过的名字。
    write_json(archive, {**data, "clips": [dict(c, name="A") for c in data["clips"]]})
    assert [c["name"] for c in build_sample(directory, archive, 1, out)["clips"]] == ["A"] * 4


def test_sample_refuses_a_plan_made_for_other_segments(tmp_path: Path) -> None:
    directory, _ = make_episode(tmp_path, "ep1")
    other, other_rows = make_episode(tmp_path, "ep2")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    make_groups(candidate, other, other_rows, ["speaker_001"] * 5)
    make_groups(baseline, other, other_rows, ["speaker_002"] * 5)
    out = tmp_path / "plan.json"
    build_plan(candidate, baseline, [], out)

    with pytest.raises(ValueError, match="计划里没有 ep1"):
        build_sample(directory, tmp_path / "ep1-short.json", 1, out)


def test_known_names_drops_special_labels_and_deduplicates(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    write_json(first, {"source": "a.wav", "clips": [{"name": "teo"}, {"name": "__unclear__"}]})
    write_json(second, {"source": "b.wav", "clips": [{"name": "teo"}, {"name": "皇帝"}, {}]})
    assert known_names([first, second]) == ["teo", "皇帝"]


def test_roster_falls_back_to_the_archives_the_plan_recorded(tmp_path: Path) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    make_groups(candidate, directory, rows, ["speaker_001"] * 5)
    make_groups(baseline, directory, rows, ["speaker_002"] * 5)
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {"source": f"{directory / 'ep1.wav'}", "clips": [dict(rows[0], name="teo")]},
    )
    out = tmp_path / "plan.json"
    build_plan(candidate, baseline, [annotation], out)

    assert known_names(_roster_archives(None, out)) == ["teo"]
    assert _roster_archives([annotation], None) == [annotation]
    assert _roster_archives(None, None) == []

    annotation.unlink()
    with pytest.raises(ValueError, match="已不在原处"):
        _roster_archives(None, out)


def test_reference_clips_group_old_labels_by_name_and_find_moved_audio(tmp_path: Path) -> None:
    root = tmp_path / "episodes"
    root.mkdir()
    first, first_rows = make_episode(root, "ep1")
    _, second_rows = make_episode(root, "ep2")
    old = tmp_path / "ep1-old.json"
    other = tmp_path / "ep2-old.json"
    # 旧归档记的是搬走以前的路径，只有文件名还对得上。
    write_json(
        old,
        {
            "source": "runs/probe/ep1/separated/ep1.wav",
            "clips": [
                dict(first_rows[0], name="teo"),
                dict(first_rows[1], name="__multiple__"),
                dict(first_rows[2], name=None),
            ],
        },
    )
    write_json(
        other,
        {"source": "runs/probe/ep2/separated/ep2.wav", "clips": [dict(second_rows[0], name="teo")]},
    )

    history = reference_clips([old, other], first)
    assert list(history) == ["teo"]
    assert [(e["episode"], e["stamp"]) for e in history["teo"]] == [
        ("ep1", "00:00.00"),
        ("ep2", "00:00.00"),
    ]
    assert len({e["file"] for e in history["teo"]}) == 2
    assert all(e["vocals"].endswith(".wav") for e in history["teo"])


def test_reference_clips_skip_archives_whose_audio_is_gone(tmp_path: Path) -> None:
    root = tmp_path / "episodes"
    root.mkdir()
    directory, rows = make_episode(root, "ep1")
    stray = tmp_path / "stray.json"
    write_json(stray, {"source": "somewhere/else.wav", "clips": [dict(rows[0], name="teo")]})
    assert reference_clips([stray], directory) == {}


def test_all_clips_sample_takes_the_whole_episode_in_time_order(tmp_path: Path) -> None:
    directory, rows = make_episode(tmp_path, "ep1")
    data = build_sample(directory, tmp_path / "ep1-full.json", count=2, every=True)
    assert [c["clip_id"] for c in data["clips"]] == [row["id"] for row in rows]
    assert "seed" not in data and "plan" not in data
    with pytest.raises(ValueError, match="只能选一个"):
        build_sample(directory, tmp_path / "clash.json", 2, tmp_path / "plan.json", every=True)


def test_known_names_also_reads_a_plain_name_list(tmp_path: Path) -> None:
    archive = tmp_path / "a.json"
    roster = tmp_path / "names.json"
    write_json(archive, {"source": "a.wav", "clips": [{"name": "teo"}, {"name": "teo"}]})
    write_json(roster, {"names": ["皇帝", "teo", "__unclear__"]})
    # 归档里的名字按条数在前，词表补上没标过的，重复的不再出现一次。
    assert known_names([archive, roster]) == ["teo", "皇帝"]
    assert known_names([roster]) == ["皇帝", "teo"]


def test_reference_clips_ignore_a_name_list_with_no_segments(tmp_path: Path) -> None:
    root = tmp_path / "episodes"
    root.mkdir()
    directory, _ = make_episode(root, "ep1")
    roster = tmp_path / "names.json"
    write_json(roster, {"names": ["teo"]})
    assert reference_clips([roster], directory) == {}


def test_all_clips_archive_picks_up_segments_added_later(tmp_path: Path) -> None:
    directory, _ = make_episode(tmp_path, "ep1")
    archive = tmp_path / "ep1-full.json"
    data = build_sample(directory, archive, count=1, every=True)
    write_json(archive, {**data, "clips": [dict(c, name="A") for c in data["clips"]]})

    # 片段表后来补进两条，已有片段一条没动。
    extra = [*SPANS, {"start": 7.0, "end": 7.4}, {"start": 8.0, "end": 8.6}]
    write_json(directory / "segments.json", segment_rows("ep1", extra))
    grown = build_sample(directory, archive, count=1, every=True)

    assert len(grown["clips"]) == len(SPANS) + 2
    assert [c["name"] for c in grown["clips"]] == ["A"] * len(SPANS) + [None, None]
    assert [c["start"] for c in grown["clips"]] == sorted(c["start"] for c in grown["clips"])
    assert read_json(archive) == grown
    # 不是整集标的时候不动已有归档。
    assert build_sample(directory, archive, count=1) == grown
