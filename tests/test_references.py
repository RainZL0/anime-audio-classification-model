from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from avs.evaluation.identity import evaluate
from avs.evaluation.references import (
    assign_from_references,
    link_reference_groups,
    reference_experiment,
)
from avs.project import read_json, write_json


def fixture() -> dict[str, Any]:
    return {
        "schema": "avs.groups.v1",
        "strategy": "global_average",
        "episodes": {"ep1": {"vocals": "ep1.wav"}},
        "assignments": [
            {"id": str(i), "episode": "ep1", "start": i * 2, "end": i * 2 + 1, "speaker": g}
            for i, g in enumerate(["g1", "g1", "g2", "g2", "g3", None])
        ],
    }


def test_reference_links_preserve_unknown_and_reject_conflicts() -> None:
    data = fixture()
    before = deepcopy(data)
    result = link_reference_groups(data, {"0": "A", "2": "A"})
    groups = [r["speaker"] for r in result["assignments"]]
    assert groups[0] == groups[1] == groups[2] == groups[3]
    assert groups[4] != groups[0]
    assert groups[5] is None
    assert data == before
    conflict = link_reference_groups(data, {"0": "A", "1": "B", "2": "A"})
    assert conflict["support"]["conflicting_groups"] == ["g1"]
    assert conflict["assignments"][0]["speaker"] != conflict["assignments"][2]["speaker"]
    with pytest.raises(ValueError, match="参考片段"):
        link_reference_groups(data, {"5": "A"})


def test_reference_labels_are_excluded_and_hidden_contamination_is_counted(tmp_path: Path) -> None:
    data = fixture()
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {
            "source": "ep1.wav",
            "clips": [
                dict(r, name="A" if i < 4 else "B") for i, r in enumerate(data["assignments"])
            ],
        },
    )
    base = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    write_json(base, data)
    write_json(candidate, link_reference_groups(data, {"0": "A", "2": "A"}))
    before = evaluate(base, [annotation], {"0", "2"})
    after = evaluate(candidate, [annotation])
    assert before["metrics"]["labeled_clips"] == after["metrics"]["labeled_clips"] == 4
    assert after["excluded_support_labels"] == 2
    assert before["metrics"]["missed_same_person_pairs"] == 2
    assert after["metrics"]["missed_same_person_pairs"] == 1
    assert after["metrics"]["correct_same_person_pairs"] == 1
    # 一个未用作参考的 B 混进 g2，整组传播会把错合扩大，评分必须揭示它。
    data["assignments"][4]["speaker"] = "g2"
    write_json(base, data)
    write_json(candidate, link_reference_groups(data, {"0": "A", "2": "A"}))
    assert evaluate(base, [annotation], {"0", "2"})["metrics"]["false_merged_pairs"] == 1
    assert evaluate(candidate, [annotation])["metrics"]["false_merged_pairs"] == 2


def test_experiment_retains_splits_and_fixed_candidate(tmp_path: Path) -> None:
    data = fixture()
    base, annotation = tmp_path / "base.json", tmp_path / "truth.json"
    write_json(base, data)
    write_json(
        annotation,
        {"source": "ep1.wav", "clips": [dict(r, name="A") for r in data["assignments"][:4]]},
    )
    report = reference_experiment(base, [annotation], tmp_path / "experiment", ["A"])
    assert len(report["results"]) == 40
    for trial in report["results"]:
        expected = 4 - trial["references_per_role"]
        assert trial["baseline"]["labeled_clips"] == expected
        assert trial["with_references"]["labeled_clips"] == expected
    candidate = read_json(tmp_path / "experiment/candidate.json")
    assert candidate["support"]["labels"] == report["results"][20]["support"]
    with pytest.raises(ValueError, match="已存在"):
        reference_experiment(base, [annotation], tmp_path / "experiment", ["A"])


def test_nearest_reference_does_not_chain_or_force_ambiguous_clips() -> None:
    data = fixture()
    records = data["assignments"][:5]
    angles = np.deg2rad([0, 30, 60, 60, 180])
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    result = assign_from_references(data, {"0": "A"}, records, vectors, 0.2)
    groups = [r["speaker"] for r in result["assignments"]]
    assert groups[0] == groups[1]
    assert groups[2] == groups[3] != groups[0]  # 不能借已预测的 30 度片段继续连向 60 度。
    assert groups[4] != groups[0]
    assert groups[5] is None
    vectors[1], vectors[2] = [2**-0.5, 2**-0.5], [0, 1]
    ambiguous = assign_from_references(data, {"0": "A", "2": "B"}, records, vectors, 0.4)
    assert ambiguous["assignments"][1]["speaker"] not in {
        ambiguous["assignments"][0]["speaker"],
        ambiguous["assignments"][2]["speaker"],
    }
