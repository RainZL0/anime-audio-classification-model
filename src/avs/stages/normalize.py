"""分数归一化：把配对分数放到各自的干扰分布上再比，而不是直接比原始余弦。

**为什么要做。** 全量标签实测显示，同人配对的距离随片段变短、跨集而系统性变大（中位距离
短于 1.5 秒 0.496、1.5-3 秒 0.416、3-6 秒 0.322）。也就是说一条短片段跟谁都不太像，
不只是跟同角色不像。单一全局阈值没法同时照顾这两种片段：卡在长片段合适的位置，短片段
就全连不上。归一化正是冲着这种整体偏移去的，先看这条片段跟一堆无关片段有多像，再问
「这一对比它平常的水平高出多少」。

**两种做法。** `snorm` 用全部干扰片段的均值与标准差；`asnorm` 只取最像的 `k` 条来算，
理由是远处的干扰片段对判断近邻没有信息量。这里的干扰集就是本批全部片段（排除自己），
没有独立的干扰集可用，所以 `asnorm` 取到的「最像的 k 条」里难免混进同角色片段，
削弱归一化的效果，这一点在解读结果时要记住。

返回的是归一化后的相似度（越大越像），不是距离；转成距离由调用方决定，因为归一化分数
是标准分，量纲和余弦距离不一样，不能直接套原来的阈值。
"""

from __future__ import annotations

from typing import Any

NORMS = ("none", "snorm", "asnorm")
ASNORM_K = 100
"""asnorm 取多少条最像的干扰片段。取自本批 485 条的量级，约五分之一。"""


def normalized_similarity(vectors: Any, method: str = "none", k: int = ASNORM_K) -> Any:
    """成对相似度，按 `method` 做分数归一化。`vectors` 必须是单位向量。"""
    import numpy as np

    if method not in NORMS:
        raise ValueError(f"归一化只能是 {', '.join(NORMS)}，收到 {method}")
    similarity = np.asarray(vectors, dtype=np.float64) @ np.asarray(vectors, dtype=np.float64).T
    if method == "none" or len(similarity) < 3:
        return similarity

    count = len(similarity)
    cohort = similarity.copy()
    np.fill_diagonal(cohort, -np.inf)
    if method == "snorm":
        # 自己不算进自己的干扰分布，所以先把对角挖掉再统计。
        keep = ~np.eye(count, dtype=bool)
        rows = similarity[keep].reshape(count, count - 1)
    else:
        take = max(2, min(k, count - 1))
        rows = np.sort(cohort, axis=1)[:, -take:]
    mean = rows.mean(axis=1)
    spread = rows.std(axis=1)
    spread[spread < 1e-9] = 1e-9
    left = (similarity - mean[:, None]) / spread[:, None]
    right = (similarity - mean[None, :]) / spread[None, :]
    return 0.5 * (left + right)
