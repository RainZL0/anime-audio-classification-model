"""量一件事：声纹距离到底能不能把人分开。

**为什么这是当前最该量的东西。** 整个分组方案建立在「同一个人的两段声音，指纹会很接近」
这个前提上，而分界线是 `HOW_IT_WORKS.md` 4.5 里说的「整个工具最关键、也最难凭空定的一个
数字」。`STATUS.md` 里记着一个坏消息：早先在这部片子上量到同一个人中位数 0.746、不同人
中位数 0.901，两条分布严重重叠。如果这是真的，分界线根本画不出来，后面分组和导出写了也白写。

**早先那个数字自己也不可信**，因为它的「同一个人」来自当时那批可疑的分组标签，属于循环论证。
现在条件好了：音质筛选留下的是干净片段，在它们上面重量一次更有意义。

**但循环论证只是减轻了，没有消除。** 这里的「同一个人」仍然是切段认人给的标签，不是人工
标注。所以这份报告的正确读法是：

- **结果差** → 是硬结论。干净片段上都分不开，那这条路有问题。
- **结果好** → 只是必要条件，不是充分条件。还得人工听十几条确认标签才算数。

术语看 `GLOSSARY.md`：声音指纹、余弦相似度、阈值。
"""

from __future__ import annotations

from typing import Any

CLOSE_ENOUGH = 1e-12


def _average_ranks(values: Any) -> Any:
    """把一组数换成名次，并列的取平均名次。手写是为了不引入新依赖。"""
    import numpy as np

    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    head = 0
    while head < len(ordered):
        tail = head
        while tail + 1 < len(ordered) and abs(ordered[tail + 1] - ordered[head]) <= CLOSE_ENOUGH:
            tail += 1
        ranks[order[head : tail + 1]] = (head + tail) / 2.0 + 1.0
        head = tail + 1
    return ranks


def _separability(same: Any, diff: Any) -> float:
    """随便挑一对，同一个人的距离确实更小的概率。0.5 是瞎猜，1.0 是完全分得开。"""
    import numpy as np

    ranks = _average_ranks(np.concatenate([same, diff]))
    n_same, n_diff = len(same), len(diff)
    u = n_same * n_diff + n_same * (n_same + 1) / 2.0 - ranks[:n_same].sum()
    return float(u / (n_same * n_diff))


def _best_threshold(same: Any, diff: Any) -> tuple[float, float, float, float]:
    """扫一遍分界线，找两类错误最接近的那个点。

    返回（分界线, 认错率, 漏认率, 两者平均）。认错率是「不同人被判成同一个人」的比例，
    漏认率是「同一个人被判成不同人」的比例。两者平均就是常说的等错误率。
    """
    import numpy as np

    candidates = np.unique(np.concatenate([same, diff]))
    best = (float("nan"), 1.0, 1.0, 1.0)
    best_gap = float("inf")
    for threshold in candidates:
        false_accept = float((diff <= threshold).mean())
        false_reject = float((same > threshold).mean())
        gap = abs(false_accept - false_reject)
        if gap < best_gap:
            best_gap = gap
            best = (float(threshold), false_accept, false_reject, (false_accept + false_reject) / 2)
    return best


def distance_report(meta: list[Any], vectors: Any) -> dict[str, Any]:
    """比较所有片段两两之间的距离，按「标签相同」和「标签不同」分成两堆。

    vectors 每行必须已经做过长度归一（`embeddings.extract` 出来的就是）。
    距离用 1 减余弦相似度，0 表示一模一样，越大越不像。
    """
    import numpy as np

    labels = np.array([m.speaker for m in meta])
    similarity = vectors @ vectors.T
    distance = 1.0 - similarity

    upper = np.triu_indices(len(meta), k=1)
    pair_distance = distance[upper]
    pair_same = labels[upper[0]] == labels[upper[1]]

    same = pair_distance[pair_same]
    diff = pair_distance[~pair_same]
    if len(same) == 0 or len(diff) == 0:
        raise RuntimeError("同人对或者不同人对为空，没法比。检查标签是不是只有一个说话人")

    threshold, false_accept, false_reject, equal_error = _best_threshold(same, diff)

    def spread(values: Any) -> dict[str, float]:
        low, mid, high = (float(x) for x in np.percentile(values, [25, 50, 75]))
        return {
            "pairs": len(values),
            "p25": round(low, 4),
            "median": round(mid, 4),
            "p75": round(high, 4),
        }

    names, counts = np.unique(labels, return_counts=True)
    speakers = {str(n): int(c) for n, c in zip(names, counts, strict=True)}

    return {
        "segments": len(meta),
        "speakers": speakers,
        "same_speaker": spread(same),
        "different_speaker": spread(diff),
        "gap": round(float(np.median(diff) - np.median(same)), 4),
        "separability": round(_separability(same, diff), 4),
        "best_threshold": round(threshold, 4),
        "false_accept": round(false_accept, 4),
        "false_reject": round(false_reject, 4),
        "equal_error": round(equal_error, 4),
        "caveat": (
            "「同一个人」用的是切段认人给的标签，不是人工标注。结果差是硬结论，"
            "结果好只是必要条件，还得人工听过才算数。"
        ),
    }


def format_report(model: str, report: dict[str, Any]) -> str:
    """把报告压成几行能一眼看懂的话。"""
    same = report["same_speaker"]
    diff = report["different_speaker"]
    lines = [
        f"[{model}] {report['segments']} 条片段，{len(report['speakers'])} 个说话人",
        f"  同一个人  中位数 {same['median']}"
        f"  四分位 {same['p25']} 到 {same['p75']}  （{same['pairs']} 对）",
        f"  不同的人  中位数 {diff['median']}"
        f"  四分位 {diff['p25']} 到 {diff['p75']}  （{diff['pairs']} 对）",
        f"  两者拉开 {report['gap']}",
        f"  分得开的程度 {report['separability']}（0.5 等于瞎猜，1.0 是完全分得开）",
        f"  最好的分界线 {report['best_threshold']}，此时等错误率 {report['equal_error']:.1%}",
    ]
    return "\n".join(lines)
