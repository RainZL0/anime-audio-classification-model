"""Linking rules only change which distances count as linked.

The mutual-nearest-neighbour rule must limit chain-style spreading.
"""

from __future__ import annotations

import numpy as np
import pytest

from avs.stages.cluster import METHODS, cluster


def _unit(rows: list[list[float]]) -> np.ndarray:
    matrix = np.array(rows, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def _same(labels: np.ndarray, i: int, j: int) -> bool:
    return bool(labels[i] == labels[j])


def test_single_chains_where_average_splits() -> None:
    # Three clips lie along one arc: neighbours are about 0.13 apart,
    # and the two ends are about 0.5 apart.
    chain = _unit([[1, 0], [0.87, 0.5], [0.5, 0.87]])
    single = cluster(chain, 0.2, "single")
    average = cluster(chain, 0.2, "average")
    complete = cluster(chain, 0.2, "complete")
    assert _same(single, 0, 2)
    assert not _same(average, 0, 2)
    assert not _same(complete, 0, 2)


def test_mutual_knn_links_only_reciprocal_neighbours_within_threshold() -> None:
    # Group A's four clips are all close to each other. Group B's two clips are each
    # other's nearest neighbour. C is about 0.3 from A, but it is not among A's nearest neighbours.
    vectors = _unit(
        [
            [1, 0, 0],
            [0.99, 0.1, 0],
            [0.99, 0, 0.1],
            [0.99, 0.07, 0.07],
            [0, 1, 0],
            [0, 0.98, 0.2],
            [0.7, 0, 0.71],
        ]
    )
    labels = cluster(vectors, 0.5, "mutual_knn")
    assert len({labels[i] for i in range(4)}) == 1
    assert _same(labels, 4, 5)
    assert not _same(labels, 0, 4)
    assert labels[6] not in {labels[0], labels[4]}
    # At the same threshold, single linkage chains C into group A.
    # The mutual-nearest-neighbour rule does not.
    assert _same(cluster(vectors, 0.5, "single"), 0, 6)
    assert len(set(cluster(vectors, 0.001, "mutual_knn"))) == 7


def test_rejects_unknown_method_and_handles_tiny_inputs() -> None:
    with pytest.raises(ValueError, match="Linking rule"):
        cluster(_unit([[1, 0], [0, 1]]), 0.5, "centroid")
    for method in METHODS:
        assert list(cluster(_unit([[1, 0]]), 0.5, method, [1.0])) == [0]
        assert len(cluster(np.empty((0, 3)), 0.5, method, [])) == 0


def test_two_stage_attaches_short_clips_only_to_a_clearly_nearest_long_group() -> None:
    # Long clips 0-2; short clips 3-5. Clip 3 is clearly close to A.
    # Clip 4 is equally far from A's nearest member and from B, so it is not attached.
    # Clip 5 is far from everything, and not close to clip 4 either.
    vectors = _unit(
        [
            [1, 0, 0],
            [0.98, 0.2, 0],
            [0, 1, 0],
            [0.95, 0.31, 0],
            [0.632, 0.774, 0],
            [0, 0, 1],
        ]
    )
    durations = [2, 2, 3, 1, 1.2, 0.8]
    labels = cluster(vectors, 0.5, "two_stage", durations)
    assert _same(labels, 0, 1) and not _same(labels, 0, 2)
    assert _same(labels, 3, 0)
    assert labels[4] not in {labels[0], labels[2]}
    assert labels[5] not in {labels[0], labels[2], labels[4]}
    assert len(set(labels)) == 4
    with pytest.raises(ValueError, match="duration"):
        cluster(vectors, 0.5, "two_stage")
    # When all clips are short or all are long, it falls back to average linkage.
    assert list(cluster(vectors, 0.5, "two_stage", [1] * 6)) == list(cluster(vectors, 0.5))
    assert list(cluster(vectors, 0.5, "two_stage", [2] * 6)) == list(cluster(vectors, 0.5))
