"""连接规则只改变哪些距离算连上；互为近邻规则必须限制链式传播。"""

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
    # 三条片段沿一条弧排开：相邻距离约 0.13，两端距离约 0.5。
    chain = _unit([[1, 0], [0.87, 0.5], [0.5, 0.87]])
    single = cluster(chain, 0.2, "single")
    average = cluster(chain, 0.2, "average")
    complete = cluster(chain, 0.2, "complete")
    assert _same(single, 0, 2)
    assert not _same(average, 0, 2)
    assert not _same(complete, 0, 2)


def test_mutual_knn_links_only_reciprocal_neighbours_within_threshold() -> None:
    # A 组四条互相紧挨；B 组两条互为最近邻；C 离 A 约 0.3，但 A 的近邻里排不上它。
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
    # 同一阈值下单连接会把 C 链进 A 组；互为近邻规则不会。
    assert _same(cluster(vectors, 0.5, "single"), 0, 6)
    assert len(set(cluster(vectors, 0.001, "mutual_knn"))) == 7


def test_rejects_unknown_method_and_handles_tiny_inputs() -> None:
    with pytest.raises(ValueError, match="连接规则"):
        cluster(_unit([[1, 0], [0, 1]]), 0.5, "centroid")
    for method in METHODS:
        assert list(cluster(_unit([[1, 0]]), 0.5, method)) == [0]
        assert len(cluster(np.empty((0, 3)), 0.5, method)) == 0
