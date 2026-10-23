"""Setting the threshold from the pool.

Also the report that measures how the threshold changes with pool size.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.evaluation.drift import drift
from avs.evaluation.identity import pair_counts
from avs.project import cache_signature, segment_rows, write_json
from avs.stages.cluster import pool_threshold


def _unit(matrix: np.ndarray) -> np.ndarray:
    return (matrix / np.linalg.norm(matrix, axis=1, keepdims=True)).astype(np.float32)


def episode(root: Path, name: str, vectors: np.ndarray) -> Path:
    """One episode where every clip has a voiceprint; the directions are given by the caller."""
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    sf.write(vocals, np.zeros(16000), 16000)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(name.encode())
    write_json(
        directory / "episode.json",
        {
            "schema": "avs.episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(analysis),
            "source": str(vocals),
            "sample_rate": 16000,
        },
    )
    rows = segment_rows(name, [{"start": i, "end": i + 0.9} for i in range(len(vectors))])
    write_json(directory / "segments.json", rows)
    cache = directory / "embeddings/redimnet2-b6"
    cache.mkdir(parents=True)
    np.save(cache / "vectors.npy", _unit(vectors))
    write_json(cache / "metadata.json", rows)
    write_json(cache / "cache.json", cache_signature(directory, "redimnet2-b6"))
    return directory


def test_pair_counts_matches_counting_every_pair_by_hand() -> None:
    truth = ["A", "A", "B", "B", "C"]
    predicted = [0, 0, 0, 1, 1]
    hits = false_merges = missed = 0
    for i in range(len(truth)):
        for j in range(i):
            same_person = truth[i] == truth[j]
            same_group = predicted[i] == predicted[j]
            hits += int(same_person and same_group)
            false_merges += int(not same_person and same_group)
            missed += int(same_person and not same_group)
    assert pair_counts(truth, predicted) == (hits, false_merges, missed)
    assert pair_counts(truth, predicted) == (1, 3, 1)
    with pytest.raises(ValueError, match="different lengths"):
        pair_counts(truth, predicted[:2])


def test_pool_threshold_reads_the_quantile_of_this_pool() -> None:
    # Two clips almost coincide and the rest are at right angles, so the
    # closest pair sets the 1st percentile.
    vectors = _unit(np.array([[1, 0, 0], [1, 0.02, 0], [0, 1, 0], [0, 0, 1]], dtype=float))
    distances = [1 - float(a @ b) for i, a in enumerate(vectors) for b in vectors[:i]]
    assert pool_threshold(vectors, 2.0, 0.01) == pytest.approx(
        2.0 * float(np.quantile(distances, 0.01)), rel=1e-6
    )
    with pytest.raises(ValueError, match="quantile"):
        pool_threshold(vectors, 2.0, 0.0)
    with pytest.raises(ValueError, match="multiplier"):
        pool_threshold(vectors, 0.0)
    with pytest.raises(ValueError, match="two clips"):
        pool_threshold(vectors[:1], 2.0)


def _corpus(tmp_path: Path) -> tuple[list[Path], Path]:
    rng = np.random.default_rng(0)
    scored = episode(
        tmp_path,
        "ep1",
        np.array([[1, 0, 0], [0.95, 0.1, 0], [0, 1, 0], [0.05, 0.98, 0]], dtype=float),
    )
    other = episode(tmp_path, "ep2", rng.normal(size=(6, 3)))
    rows = [
        {"start": float(i), "end": i + 0.9, "name": name}
        for i, name in enumerate(["A", "A", "B", "B"])
    ]
    annotation = tmp_path / "truth.json"
    write_json(annotation, {"source": "ep1.wav", "clips": rows})
    return [scored, other], annotation


def test_drift_holds_the_scored_episode_fixed_and_reports_both_lines(tmp_path: Path) -> None:
    episodes, annotation = _corpus(tmp_path)
    out = tmp_path / "drift.json"
    report = drift(
        episodes,
        "ep1",
        [annotation],
        out,
        model="redimnet2-b6",
        threshold=0.5,
        multiplier=2.0,
        steps=3,
        seeds=2,
    )
    assert report["schema"] == "avs.drift.v1"
    assert report["labeled_clips"] == 4
    assert report["roles"] == 2
    # Three pool sizes: add none, add half, add all. The scored episode always
    # stays in the pool in full.
    assert [row["pool_clips"] for row in report["summary"]] == [4, 7, 10]
    assert all(row["fixed_threshold"] == 0.5 for row in report["summary"])
    assert all(
        run["relative_threshold"] == pytest.approx(2.0 * run["pool_quantile_distance"], abs=5e-4)
        for run in report["runs"]
    )
    assert out.exists()
    with pytest.raises(ValueError, match="already exists"):
        drift(episodes, "ep1", [annotation], out, model="redimnet2-b6", multiplier=2.0)


def test_drift_refuses_labels_that_do_not_belong_to_the_scored_episode(tmp_path: Path) -> None:
    episodes, annotation = _corpus(tmp_path)
    with pytest.raises(ValueError, match="No labels for ep2"):
        drift(
            episodes,
            "ep2",
            [annotation],
            tmp_path / "a.json",
            model="redimnet2-b6",
            multiplier=2.0,
        )
    outside = tmp_path / "outside.json"
    write_json(outside, {"source": "another-show.wav", "clips": []})
    with pytest.raises(ValueError, match="not in these episode folders"):
        drift(
            episodes,
            "ep1",
            [outside],
            tmp_path / "b.json",
            model="redimnet2-b6",
            multiplier=2.0,
        )
