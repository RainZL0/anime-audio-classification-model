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

POOL_QUANTILE = 0.01
"""按池子定分界线时取的分位：池子里全部配对距离由近到远排开，取第 1% 那个距离。

取这么低的分位是因为它跟着「同一角色的配对占全部配对的比例」走。池子里角色越多，
靠得很近的那一小撮配对就越稀，这个距离就越大，方向正好和分界线需要挪动的方向一致。
中位数之类的高分位几乎全是不同角色的配对，池子变大也不动，用不上。"""

POOL_MULTIPLIERS = {"anime-va": 1.275}
"""按池子定分界线时乘的倍数，一个模型一个。乘出来的值就是分界线。

1.275 是这样定出来的：现在三集 1176 条片段拼成的池子上，它正好乘出 anime-va 现用的 0.70。
**所以今天这条规则和固定 0.70 分组结果一样，语料继续长大才开始分岔**，分岔的方向是分界线
跟着池子往外挪，抵消掉「池子越大合并越保守」。

倍数决定的是松紧，跟能不能稳住是两回事。倍数取 1.38（在只有第 3 集时乘出 0.70）也一样稳，
但那是个松得多的位置：第 3 集连上的从 2095 涨到 3075，第 1 集的错误合并却从 11 涨到 155。
错误合并是这个项目里更贵的那种错，所以取保守的那个。

**这个倍数是在已有三集的标签上挑的，还没有独立检验。** 见 EXPERIMENTS.md。"""

MAX_QUANTILE_PAIRS = 20_000_000
"""算分位时最多用多少对距离。再多就随机抽这么多对，免得整张距离表撑爆内存。
13 集大约 5000 条片段、1250 万对，还在这个数以内。"""


def pool_threshold(vectors: Any, multiplier: float, quantile: float = POOL_QUANTILE) -> float:
    """按池子自己的距离定分界线，而不是记死一个数。

    固定分界线会随片段池变大而失准：同一个数，池子越大合并越保守（见 HISTORY.md）。
    这里改成先看这个池子内部的距离长什么样，再按同一个比例定分界线。
    """
    import numpy as np

    if not 0 < quantile < 1:
        raise ValueError("分位必须在 0 和 1 之间")
    if not multiplier > 0:
        raise ValueError("倍数必须大于 0")
    if len(vectors) < 2:
        raise ValueError("至少要两条片段才能量池子内部的距离")
    total = len(vectors) * (len(vectors) - 1) // 2
    if total <= MAX_QUANTILE_PAIRS:
        from scipy.spatial.distance import pdist

        distances = pdist(vectors, metric="cosine")
    else:
        rng = np.random.default_rng(0)
        rows = rng.integers(0, len(vectors), MAX_QUANTILE_PAIRS)
        cols = rng.integers(0, len(vectors) - 1, MAX_QUANTILE_PAIRS)
        cols += cols >= rows  # 不要拿片段和自己配对，那个距离恒为 0
        distances = 1 - np.einsum("ij,ij->i", vectors[rows], vectors[cols])
    return float(np.quantile(distances, quantile) * multiplier)


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
