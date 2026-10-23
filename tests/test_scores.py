"""Score normalisation and separation.

Normalisation changes whether one threshold can still be used across different clips.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.evaluation.scores import compare_norms, duration_bin, separation
from avs.project import cache_signature, read_json, segment_rows, write_json
from avs.stages.normalize import normalized_similarity


def unit(rows: list[list[float]]) -> np.ndarray:
    matrix = np.array(rows, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def make_episode(root: Path, name: str, vectors: np.ndarray) -> Path:
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    sf.write(vocals, np.zeros(44100 * (2 * len(vectors) + 1), dtype=np.float32), 44100)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(b"fixture")
    write_json(
        directory / "episode.json",
        {
            "schema": "avs.episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(analysis),
            "source": str(vocals),
            "sample_rate": 44100,
        },
    )
    spans = [{"start": 2.0 * i, "end": 2.0 * i + 1.6} for i in range(len(vectors))]
    rows = segment_rows(name, spans)
    write_json(directory / "segments.json", rows)
    cache = directory / "embeddings/redimnet2-b6"
    cache.mkdir(parents=True)
    np.save(cache / "vectors.npy", vectors.astype(np.float32))
    write_json(cache / "metadata.json", rows)
    write_json(cache / "cache.json", cache_signature(directory, "redimnet2-b6"))
    return directory


def test_normalisation_pulls_down_a_clip_that_is_close_to_everything() -> None:
    """Normalisation exists for this case: a clip that looks a bit like everything
    gives a high score that means nothing.

    Clip 0 sits in the middle of a crowd of clips, and clip 1 is 10 degrees away
    from it. Clips 2 and 3 are a separate pair far away, 12 degrees apart.
    With raw cosine similarity, the 0-1 score is higher, but only because clip 0
    is similar to everything. After normalising each clip by its own distribution
    of other scores, 2-3 is the pair that really stands out.
    """
    angle = np.deg2rad
    vectors = unit(
        [
            [1.0, 0.0, 0.0],
            [float(np.cos(angle(10))), float(np.sin(angle(10))), 0.0],
            [0.0, 0.0, 1.0],
            [0.0, float(np.sin(angle(12))), float(np.cos(angle(12)))],
            [float(np.cos(angle(25))), float(np.sin(angle(25))), 0.0],
            [float(np.cos(angle(25))), -float(np.sin(angle(25))), 0.0],
            [float(np.cos(angle(35))), float(np.sin(angle(35))), 0.0],
        ]
    )
    raw = normalized_similarity(vectors, "none")
    assert raw[0][1] > raw[2][3]
    fixed = normalized_similarity(vectors, "snorm")
    assert fixed[2][3] > fixed[0][1]
    assert np.allclose(fixed, fixed.T, atol=1e-6)


def test_normalisation_rejects_unknown_method_and_passes_tiny_pools() -> None:
    vectors = unit([[1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(ValueError, match="Normalization must be one of"):
        normalized_similarity(vectors, "zzz")
    # With fewer than three clips there is no distractor set to use, so the raw cosine is returned.
    assert np.allclose(normalized_similarity(vectors, "snorm"), vectors @ vectors.T)


def test_separation_reads_higher_is_more_alike() -> None:
    same = np.array([0.9, 0.8, 0.85])
    other = np.array([0.1, 0.2, 0.15])
    own = separation(same, other)
    assert own["auc"] == 1.0
    assert own["eer"] == 0.0
    assert own["same_pairs"] == 3
    assert separation(np.array([]), other)["auc"] is None
    # When the two sets fully overlap, the AUC should drop to about 0.5.
    assert 0.4 <= separation(same, same)["auc"] <= 0.6


def test_duration_bins_cover_every_length() -> None:
    assert duration_bin(0.4) == "0-0.5s"
    assert duration_bin(0.7) == "0.5-1s"
    assert duration_bin(1.2) == "1-1.5s"
    assert duration_bin(1.5) == "1.5-3s"
    assert duration_bin(5.9) == "3-6s"
    assert duration_bin(20.0) == ">=6s"


def test_compare_norms_reports_each_method_and_keeps_the_old_report(tmp_path: Path) -> None:
    vectors = unit(
        [[1.0, 0.0, 0.0], [0.95, 0.1, 0.0], [0.0, 1.0, 0.0], [0.1, 0.9, 0.0], [0.0, 0.0, 1.0]]
    )
    directory = make_episode(tmp_path, "ep1", vectors)
    records = read_json(directory / "embeddings/redimnet2-b6/metadata.json")
    names = ["A", "A", "B", "B", "C"]
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {
            "source": "ep1.wav",
            "clips": [dict(row, name=name) for row, name in zip(records, names, strict=True)],
        },
    )
    out = tmp_path / "scores.json"
    report = compare_norms([directory], [annotation], ["redimnet2-b6"], out, ["none", "snorm"])
    assert [r["norm"] for r in report["results"]] == ["none", "snorm"]
    assert report["labeled_clips"] == 5
    assert report["pairs"] == 10
    assert report["results"][0]["overall"]["same_pairs"] == 2
    assert read_json(out) == report

    with pytest.raises(ValueError, match="already exists"):
        compare_norms([directory], [annotation], ["redimnet2-b6"], out)
    with pytest.raises(ValueError, match="Normalization must be one of"):
        compare_norms([directory], [annotation], ["redimnet2-b6"], tmp_path / "x.json", ["nope"])
