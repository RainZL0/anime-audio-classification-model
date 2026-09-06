"""全局片段分组，不预先把一集压成不可拆的中心点。

连接规则只改变“哪些距离算连上”，不改变声纹和距离本身：
average / single / complete 是层次聚类的三种连接；mutual_knn 只在两条片段互为对方
的 k 近邻且距离不超过阈值时连边，再取连通分量；two_stage 先只用不短于 SHORT_SECONDS
的片段做按整组平均距离合并，再把短片段挂到最近成员距离不超过阈值、且领先第二个组至少
ATTACH_MARGIN 的组；挂不上的短片段之间再做一次按整组平均距离合并，让只有短片段的角色也能成组。
诊断显示该合没合全部含短片段，所以单独处理。
"""

from __future__ import annotations

from typing import Any

METHODS = ("average", "single", "complete", "mutual_knn", "two_stage")
MUTUAL_K = 3
"""互相都是对方最近邻规则里每条片段考虑的近邻数；固定为常量，避免和阈值一起扫出过拟合的组合。"""
SHORT_SECONDS = 1.5
"""two_stage 里算作短片段的时长上限，取自诊断中该合没合配对的时长分层。"""
ATTACH_MARGIN = 0.05
"""短片段挂组时最近组必须领先第二近的组的余弦距离；与参考实验的领先幅度一致。"""


def cluster(
    vectors: Any, threshold: float = 0.5, method: str = "average", durations: Any = None
) -> Any:
    """直接比较全系列片段声纹；0.5 是待独立验证的起点。返回每条片段的组号。"""
    import numpy as np

    if method not in METHODS:
        raise ValueError(f"连接规则只能是 {', '.join(METHODS)}，收到 {method}")
    if method == "two_stage":
        if durations is None or len(durations) != len(vectors):
            raise ValueError("two_stage 需要每条片段的时长")
        return _two_stage(vectors, np.asarray(durations, dtype=float), threshold)
    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    if method == "mutual_knn":
        return _mutual_knn(vectors, threshold)
    from sklearn.cluster import AgglomerativeClustering

    return AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="cosine", linkage=method
    ).fit_predict(vectors)


def _mutual_knn(vectors: Any, threshold: float) -> Any:
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    distances = 1 - vectors @ vectors.T
    np.fill_diagonal(distances, np.inf)
    k = min(MUTUAL_K, len(vectors) - 1)
    nearest = np.argsort(distances, axis=1, kind="stable")[:, :k]
    rows = np.repeat(np.arange(len(vectors)), k)
    cols = nearest.ravel()
    forward = coo_matrix((np.ones(len(rows), dtype=bool), (rows, cols)), shape=distances.shape)
    mutual = forward.multiply(forward.T).tocoo()
    keep = distances[mutual.row, mutual.col] <= threshold
    graph = coo_matrix(
        (np.ones(int(keep.sum()), dtype=bool), (mutual.row[keep], mutual.col[keep])),
        shape=distances.shape,
    )
    return connected_components(graph, directed=False)[1]


def _two_stage(vectors: Any, durations: Any, threshold: float) -> Any:
    import numpy as np

    long_index = np.where(durations >= SHORT_SECONDS)[0]
    short_index = np.where(durations < SHORT_SECONDS)[0]
    labels = np.full(len(vectors), -1, dtype=int)
    if len(long_index):
        labels[long_index] = cluster(vectors[long_index], threshold, "average")
    if len(long_index) and len(short_index):
        long_labels = labels[long_index]
        groups = np.unique(long_labels)
        distances = 1 - vectors[short_index] @ vectors[long_index].T
        # 每个短片段到每个长片段组的“最近成员”距离；只挂到明显最近的那个组。
        nearest = np.stack([distances[:, long_labels == g].min(axis=1) for g in groups], axis=1)
        order = np.argsort(nearest, axis=1, kind="stable")
        for row, clip in enumerate(short_index):
            best = nearest[row, order[row, 0]]
            second = nearest[row, order[row, 1]] if len(groups) > 1 else np.inf
            if best <= threshold and second - best >= ATTACH_MARGIN:
                labels[clip] = groups[order[row, 0]]
    leftover = np.where(labels < 0)[0]
    if len(leftover):
        offset = int(labels.max()) + 1
        labels[leftover] = offset + cluster(vectors[leftover], threshold, "average")
    return labels
