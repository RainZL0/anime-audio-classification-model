"""在同一批片段与人工标签上比较缓存声纹，保留完整阈值曲线。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from avs.evaluation.identity import evaluate
from avs.pipeline import group, load_embeddings
from avs.project import digest, write_json


def compare(
    episodes: list[Path],
    annotations: list[Path],
    models: list[str],
    thresholds: list[float],
    out: Path,
    methods: list[str] | None = None,
) -> dict[str, Any]:
    """拒绝覆盖结果或比较不同覆盖的声纹；所有成绩均是探索，非独立验收。"""
    methods = methods or ["average"]
    if out.exists():
        raise ValueError(f"报告已存在：{out}")
    if not models or len(set(models)) != len(models) or not thresholds:
        raise ValueError("需要不重复的模型名和至少一个阈值")
    if len(set(methods)) != len(methods):
        raise ValueError("连接规则不能重复")
    coverage = None
    inputs = []
    for model in models:
        ids: set[str] = set()
        for directory in episodes:
            records, _ = load_embeddings(directory, model)
            ids.update(r["id"] for r in records)
            cache = directory / "embeddings" / model
            inputs.append(
                {
                    "episode": str(directory.resolve()),
                    "model": model,
                    "segments_sha256": digest(directory / "segments.json"),
                    "vectors_sha256": digest(cache / "vectors.npy"),
                    "metadata_sha256": digest(cache / "metadata.json"),
                    "cache_sha256": digest(cache / "cache.json"),
                }
            )
        if coverage is not None and ids != coverage:
            raise ValueError("模型覆盖的片段不同，不能直接比较")
        coverage = ids
    results: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="avs-compare-") as temp:
        for model in models:
            for method in methods:
                for index, threshold in enumerate(thresholds):
                    path = Path(temp) / f"{model}-{method}-{index}.json"
                    groups = group(episodes, path, threshold, model, method)
                    scored = evaluate(path, annotations)
                    results.append(
                        {
                            "model": model,
                            "method": method,
                            "threshold": threshold,
                            **groups["summary"],
                            **scored["metrics"],
                            "unmatched_labels": scored["unmatched_labels"],
                            "special_labels": scored["special_labels"],
                            "labeled_unassigned": scored["labeled_unassigned"],
                            "roles": scored["roles"],
                        }
                    )
    # 同时更少错误合并、更多正确连接的点才算支配；不以组数少就宣称身份更准。
    frontier = [
        row
        for row in results
        if not any(
            other["false_merged_pairs"] <= row["false_merged_pairs"]
            and other["correct_same_person_pairs"] >= row["correct_same_person_pairs"]
            and (
                other["false_merged_pairs"] < row["false_merged_pairs"]
                or other["correct_same_person_pairs"] > row["correct_same_person_pairs"]
            )
            for other in results
        )
    ]
    report = {
        "schema": "avs.comparison.v1",
        "note": "同批人工标签上的探索曲线；阈值已使用这些标签，不能作为独立验证。",
        "methods": methods,
        "embedded_clips": len(coverage or []),
        "inputs": inputs,
        "annotations": [{"path": str(p.resolve()), "sha256": digest(p)} for p in annotations],
        "results": results,
        "frontier": [
            {"model": r["model"], "method": r["method"], "threshold": r["threshold"]}
            for r in frontier
        ],
    }
    write_json(out, report)
    return report
