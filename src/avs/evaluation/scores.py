"""分数归一化值不值得接进分组：先只看同人与异人的分离度。

分组规则只决定「哪些分数算连上」，改不了分数本身。所以先在人工标签的配对上量两件事，
分不开就没必要往聚类里接：

- **排序正确率**（`auc`）：随机拿一对同角色片段和一对不同角色片段，同角色那对分数更高的比例。
  完全随机是 0.50。
- **相等错误率**（`eer`）：把分界线挪到「同角色被错误分开」和「不同角色被错误合并」这两种
  错误一样多的位置，那时候的错误率。

按片段时长和是否跨集分层，因为有些手段只在某一档上起作用，总体数字持平也可能在短片段上
有改善。
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from avs.project import write_json

DURATION_BINS = ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 3.0), (3.0, 6.0))
"""短的一端分得细：所有已知的劣势都集中在那里，1 秒上下差多少直接决定要不要把
1 秒以下的片段收进来。长的一端反正差别不大，不必细分。"""


def duration_bin(seconds: float) -> str:
    for low, high in DURATION_BINS:
        if low <= seconds < high:
            return f"{low:g}-{high:g}s"
    return f">={DURATION_BINS[-1][1]:g}s"


def separation(same: Any, other: Any) -> dict[str, Any]:
    """同角色与不同角色的分数分得开不开。分数越大表示越像。"""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    if not len(same) or not len(other):
        return {"same_pairs": len(same), "other_pairs": len(other), "auc": None, "eer": None}
    labels = np.concatenate([np.ones(len(same)), np.zeros(len(other))])
    scores = np.concatenate([same, other])
    auc = float(roc_auc_score(labels, scores))
    # 相等错误率：扫过所有候选分界，取两种错误率最接近的那一点。
    grid = np.quantile(scores, np.linspace(0, 1, 401))
    miss = np.array([float((same < cut).mean()) for cut in grid])
    false = np.array([float((other >= cut).mean()) for cut in grid])
    at = int(np.argmin(np.abs(miss - false)))
    return {
        "same_pairs": len(same),
        "other_pairs": len(other),
        "auc": round(auc, 4),
        "eer": round(float((miss[at] + false[at]) / 2), 4),
        "same_median": round(float(np.median(same)), 4),
        "other_median": round(float(np.median(other)), 4),
    }


def compare_norms(
    episodes: list[Path],
    annotations: list[Path],
    models: list[str],
    out: Path,
    methods: list[str] | None = None,
    window: float = 0.0,
) -> dict[str, Any]:
    """在人工标签的配对上，对照原始余弦与各种归一化的分离度。"""
    import numpy as np

    from avs.evaluation.diagnose import load_pool
    from avs.evaluation.identity import match_annotations
    from avs.stages.normalize import NORMS, normalized_similarity

    if out.exists():
        raise ValueError(f"报告已存在，换个文件名以保留上次结果：{out}")
    chosen = list(methods or NORMS)
    if any(m not in NORMS for m in chosen) or len(set(chosen)) != len(chosen):
        raise ValueError(f"归一化只能是 {', '.join(NORMS)}，且不能重复")

    info, records, vectors = load_pool(episodes, models, window)
    matched, unmatched, special = match_annotations(
        {"schema": "avs.groups.v1", "episodes": info, "assignments": records}, annotations
    )
    index = {row["id"]: i for i, row in enumerate(records)}
    labeled = [(index[i], name) for i, name in matched.items() if i in index]
    if len(labeled) < 3:
        raise ValueError("能精确对上的人工标签太少，无法比较分离度")

    pairs = list(itertools.combinations(sorted(labeled), 2))
    same = np.array([a[1] == b[1] for a, b in pairs])
    both_short = np.array(
        [duration_bin(min(_seconds(records[a[0]]), _seconds(records[b[0]]))) for a, b in pairs]
    )
    cross = np.array([records[a[0]]["episode"] != records[b[0]]["episode"] for a, b in pairs])
    rows = np.array([a[0] for a, _ in pairs])
    cols = np.array([b[0] for _, b in pairs])

    results = []
    for model in models:
        for method in chosen:
            scores = normalized_similarity(vectors[model], method)[rows, cols]
            entry: dict[str, Any] = {
                "model": model,
                "norm": method,
                "overall": separation(scores[same], scores[~same]),
                "by_min_duration": {
                    label: separation(
                        scores[same & (both_short == label)], scores[~same & (both_short == label)]
                    )
                    for label in sorted(set(both_short))
                },
                "cross_episode": separation(scores[same & cross], scores[~same & cross]),
                "same_episode": separation(scores[same & ~cross], scores[~same & ~cross]),
            }
            results.append(entry)

    report = {
        "schema": "avs.score_norm.v1",
        "window_seconds": window,
        "labeled_clips": len(labeled),
        "unmatched_labels": unmatched,
        "special_labels": special,
        "pairs": len(pairs),
        "results": results,
        "note": "只比较分得开不开，不做分组。作基准的无关片段就是本批全部片段，"
        "没有另一批与本作无关的片段可用，所以 asnorm 挑出的最像 k 条里会混进同一角色的"
        "片段，等于拿同角色的分数当基准，这会削弱它的效果。",
    }
    write_json(out, report)
    return report


def _seconds(row: dict[str, Any]) -> float:
    return float(row["end"]) - float(row["start"])
