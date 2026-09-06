"""标注计划：只安排候选改动过、且人工归档还没覆盖的短片段。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from avs.labeling import build_plan, build_sample
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
