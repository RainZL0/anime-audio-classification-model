"""全局片段分组，不预先把一集压成不可拆的中心点。

四种连接规则只改变“哪些距离算连上”，不改变声纹和距离本身：
average / single / complete 是层次聚类的三种连接；mutual_knn 只在两条片段互为对方
的 k 近邻且距离不超过阈值时连边，再取连通分量，用来利用近邻结构、限制链式传播。
"""

from __future__ import annotations

from typing import Any

METHODS = ("average", "single", "complete", "mutual_knn")
MUTUAL_K = 3
"""互为近邻规则里每条片段考虑的近邻数；固定为常量，避免和阈值一起扫出过拟合的组合。"""


def cluster(vectors: Any, threshold: float = 0.5, method: str = "average") -> Any:
    """直接比较全系列片段声纹；0.5 是待独立验证的起点。返回每条片段的组号。"""
    import numpy as np

    if method not in METHODS:
        raise ValueError(f"连接规则只能是 {', '.join(METHODS)}，收到 {method}")
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
