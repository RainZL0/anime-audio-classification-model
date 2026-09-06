"""分数归一化值不值得接进分组：先只看同人与异人的分离度。

分组规则只决定「哪些分数算连上」，改不了分数本身。所以先在人工标签的配对上量分离度
（AUC 与等错率），分不开就没必要往聚类里接。按片段时长和是否跨集分层，因为归一化要治的
正是这两处的系统偏移，总体数字持平也可能在短片段上有改善。
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from avs.project import write_json

DURATION_BINS = ((0.0, 1.5), (1.5, 3.0), (3.0, 6.0))


def duration_bin(seconds: float) -> str:
    for low, high in DURATION_BINS:
        if low <= seconds < high:
            return f"{low:g}-{high:g}s"
    return f">={DURATION_BINS[-1][1]:g}s"


def separation(same: Any, other: Any) -> dict[str, Any]:
    """同人与异人分数的分离程度。分数越大表示越像。"""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    if not len(same) or not len(other):
        return {"same_pairs": len(same), "other_pairs": len(other), "auc": None, "eer": None}
    labels = np.concatenate([np.ones(len(same)), np.zeros(len(other))])
    scores = np.concatenate([same, other])
    auc = float(roc_auc_score(labels, scores))
    # 等错率：扫过所有候选分界，取「同人被判开」与「异人被判合」两个错误率最接近的那点。
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

    info, records, vectors = load_pool(episodes, models)
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
        "labeled_clips": len(labeled),
        "unmatched_labels": unmatched,
        "special_labels": special,
        "pairs": len(pairs),
        "results": results,
        "note": "只比较分离度，不做聚类。干扰集就是本批全部片段，没有独立干扰集，"
        "asnorm 取到的最像 k 条里会混进同角色片段，这会削弱它的效果。",
    }
    write_json(out, report)
    return report


def _seconds(row: dict[str, Any]) -> float:
    return float(row["end"]) - float(row["start"])
