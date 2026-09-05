"""全局片段分组，不预先把一集压成不可拆的中心点。"""

from __future__ import annotations

from typing import Any


def cluster(vectors: Any, threshold: float = 0.5) -> Any:
    """直接比较全系列片段声纹，平均连接；0.5 是待独立验证的起点。"""
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    return AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="cosine", linkage="average"
    ).fit_predict(vectors)
