"""分数归一化：不直接比两条片段的相似度，先看每条片段平常能拿多少分，再比这一对高出多少。

**当初为什么想试。** 实测显示同一角色的两条片段，距离随片段变短而系统性变大（中位距离：
短于 1.5 秒 0.496、1.5-3 秒 0.416、3-6 秒 0.322）。看着像是一条短片段跟谁都不太像，
而不只是跟同角色不像。如果真是这样，同一条分界线就没法同时照顾长短两种片段：卡在长片段
合适的位置，短片段全都连不上。这里做的事就是先量出每条片段跟一堆无关片段的相似度有多高，
把这个水平线减掉，再问「这一对比它自己的水平高出多少」。

**两种算法。** `snorm` 拿全部无关片段算平均值和波动幅度；`asnorm` 只拿最像的 `k` 条算，
理由是差得很远的片段对判断近邻没什么信息量。作基准的无关片段就是本批全部片段（去掉自己），
我们没有另外一批与本作无关的片段可用，所以 `asnorm` 挑出的「最像的 k 条」里难免混进同一
角色的片段，等于拿同角色的分数当基准，这会削弱效果。

**结论是没用**，见 EXPERIMENTS。代码留着，因为它是那个结论的依据。

返回的是归一化之后的相似度（越大越像），不是距离。要转成距离由调用方自己决定：归一化后的
数值是标准分，跟余弦距离不是一个量纲，原来的分界线套不上去。
"""

from __future__ import annotations

from typing import Any

NORMS = ("none", "snorm", "asnorm")
ASNORM_K = 100
"""asnorm 拿多少条最像的片段作基准。按本批 485 条的规模取了约五分之一。"""


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
        # 一条片段不能拿自己当基准，所以先把对角线挖掉再统计。
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
