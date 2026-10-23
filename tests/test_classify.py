"""Leave-one-episode-out check.

Training uses only the other episodes. Scoring looks only at the test episode.
Roles missing from the training set still count as wrong.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avs.evaluation.classify import classify_check, predict, summarize
from avs.project import write_json
from tests.test_drift import episode


def _labels(root: Path, name: str, people: list[str]) -> Path:
    path = root / f"{name}-truth.json"
    clips = [{"start": float(i), "end": i + 0.9, "name": p} for i, p in enumerate(people)]
    write_json(path, {"source": f"{name}.wav", "clips": clips})
    return path


def test_every_method_finds_the_obvious_role() -> None:
    train = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.9]], dtype=float)
    train /= np.linalg.norm(train, axis=1, keepdims=True)
    test = np.array([[0.95, 0.05], [0.05, 0.95]])
    for method in ("nearest", "centroid", "logistic"):
        guesses, confidence = predict(method, train, ["A", "A", "B", "B"], test)
        assert guesses == ["A", "B"]
        assert all(c > 0 for c in confidence)


def test_summary_ranks_by_confidence_before_cutting() -> None:
    report = summarize(
        ["A", "A", "B", "B"], ["A", "B", "B", "A"], [0.9, 0.1, 0.8, 0.2], [0.6, 1.2, 2.0, 4.0]
    )
    assert report["accuracy"] == 0.5
    assert report["by_confidence"]["top50%"] == 1.0
    assert report["by_duration"]["0.5-1s"] == {"clips": 1, "accuracy": 1.0}
    assert report["by_duration"][">=6s"] == {"clips": 0, "accuracy": None}


def test_check_trains_on_other_episodes_and_counts_unseen_roles(tmp_path: Path) -> None:
    near_a, near_b, far = [1, 0, 0], [0, 1, 0], [0, 0, 1]
    episodes = [
        episode(tmp_path, "ep1", np.array([near_a, near_a, near_b, near_b], dtype=float)),
        episode(tmp_path, "ep2", np.array([near_a, near_b, near_b], dtype=float)),
        episode(tmp_path, "ep3", np.array([near_a, near_b, far], dtype=float)),
    ]
    annotations = [
        _labels(tmp_path, "ep1", ["A", "A", "B", "B"]),
        _labels(tmp_path, "ep2", ["A", "B", "B"]),
        _labels(tmp_path, "ep3", ["A", "B", "C"]),
    ]
    out = tmp_path / "check.json"
    report = classify_check(episodes, "ep3", annotations, out, ["redimnet2-b6"])
    assert report["train_episodes"] == {"ep1": 4, "ep2": 3}
    assert report["test_clips"] == 3
    assert report["unseen_role_clips"] == 1
    for method in ("nearest", "centroid", "logistic"):
        assert report["results"][method]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    with pytest.raises(ValueError, match="already exists"):
        classify_check(episodes, "ep3", annotations, out, ["redimnet2-b6"])
    with pytest.raises(ValueError, match="No labels for ep9"):
        classify_check(episodes, "ep9", annotations, tmp_path / "x.json", ["redimnet2-b6"])
