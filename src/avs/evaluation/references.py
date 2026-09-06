"""检验少量人工身份能否连接散成很多小组；参考标签与评分标签严格分开。"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from avs.evaluation.identity import evaluate, match_annotations
from avs.pipeline import load_embeddings
from avs.project import digest, read_json, write_json


def link_reference_groups(data: dict[str, Any], support: dict[str, str]) -> dict[str, Any]:
    """仅合并含同名参考的原组；无参考或参考冲突的原组保持独立。"""
    if data.get("schema") != "avs.groups.v1" or data.get("support"):
        raise ValueError("需要尚未使用身份参考的原始分组")
    by_id = {r["id"]: r for r in data["assignments"]}
    names: dict[str, set[str]] = defaultdict(set)
    for clip_id, name in support.items():
        if clip_id not in by_id or not by_id[clip_id]["speaker"]:
            raise ValueError("参考片段必须存在且已有声纹分组")
        if not name or name.startswith("__"):
            raise ValueError("参考必须是明确的人工角色名")
        names[by_id[clip_id]["speaker"]].add(name)
    result = deepcopy(data)
    numbers: dict[tuple[str, str], str] = {}
    merged_from: dict[str, set[str]] = defaultdict(set)
    for row in result["assignments"]:
        original = row["speaker"]
        if original is None:
            continue
        own_names = names.get(original, set())
        key = ("role", next(iter(own_names))) if len(own_names) == 1 else ("group", original)
        row["speaker"] = numbers.setdefault(key, f"speaker_{len(numbers) + 1:03d}")
        merged_from[row["speaker"]].add(original)
    counts = Counter(r["speaker"] for r in result["assignments"] if r["speaker"] is not None)
    result["base_strategy"] = data["strategy"]
    result["strategy"] = "reference_group_links"
    result["support"] = {
        "clip_ids": sorted(support),
        "labels": dict(sorted(support.items())),
        "conflicting_groups": sorted(g for g, n in names.items() if len(n) > 1),
        "merged_from": {g: sorted(old) for g, old in merged_from.items() if len(old) > 1},
        "rule": "仅连接含同名人工参考的组；整组身份一致仍是待验证假设。",
    }
    result["summary"] = {
        "clips": len(result["assignments"]),
        "groups": len(counts),
        "singleton_groups": sum(n == 1 for n in counts.values()),
        "unassigned": sum(r["speaker"] is None for r in result["assignments"]),
    }
    return result


def assign_from_references(
    data: dict[str, Any],
    support: dict[str, str],
    records: list[dict[str, Any]],
    vectors: Any,
    threshold: float,
    margin: float = 0.05,
) -> dict[str, Any]:
    """最近参考足够近且领先另一角色才归属；其余保留原组，不递归扩充参考。"""
    import numpy as np

    if not 0 < threshold <= 2 or not 0 <= margin <= 2:
        raise ValueError("距离与领先幅度必须在余弦距离范围内")
    # 共用参考有效性检查；此方法从原片段重新归属，不使用合组的结果。
    link_reference_groups(data, support)
    indices = {r["id"]: i for i, r in enumerate(records)}
    if not support or any(key not in indices for key in support):
        raise ValueError("所有参考都必须有声纹")
    roles = sorted(set(support.values()))
    distances = np.stack(
        [
            1
            - np.max(
                vectors @ vectors[[indices[k] for k, n in support.items() if n == role]].T, axis=1
            )
            for role in roles
        ],
        axis=1,
    )
    order = np.argsort(distances, axis=1)
    assigned = {}
    for i, record in enumerate(records):
        best = int(order[i, 0])
        ahead = float(distances[i, order[i, 1]] - distances[i, best]) if len(roles) > 1 else 2.0
        if distances[i, best] <= threshold and ahead >= margin:
            assigned[record["id"]] = roles[best]
    assigned.update(support)
    result = deepcopy(data)
    numbers: dict[tuple[str, str], str] = {}
    for row in result["assignments"]:
        original = row["speaker"]
        if original is None:
            continue
        key = ("role", assigned[row["id"]]) if row["id"] in assigned else ("group", original)
        row["speaker"] = numbers.setdefault(key, f"speaker_{len(numbers) + 1:03d}")
    counts = Counter(r["speaker"] for r in result["assignments"] if r["speaker"] is not None)
    result["base_strategy"] = data["strategy"]
    result["strategy"] = "nearest_reference"
    result["support"] = {
        "clip_ids": sorted(support),
        "labels": dict(sorted(support.items())),
        "distance_threshold": threshold,
        "margin": margin,
        "assigned_non_support": len(assigned.keys() - support.keys()),
        "rule": "只对原始人工参考算距离，不把预测片段作为新参考；未通过的片段保留原组。",
    }
    result["summary"] = {
        "clips": len(result["assignments"]),
        "groups": len(counts),
        "singleton_groups": sum(n == 1 for n in counts.values()),
        "unassigned": sum(r["speaker"] is None for r in result["assignments"]),
    }
    return result


def reference_experiment(
    groups_file: Path,
    annotations: list[Path],
    out: Path,
    roles: list[str],
    nearest: bool = False,
) -> dict[str, Any]:
    """每人 1/2 条参考，各用种子 0—19；不按测试成绩挑参考或保存候选。"""
    if out.exists():
        raise ValueError(f"输出目录已存在：{out}")
    data = read_json(groups_file)
    records: list[dict[str, Any]] = []
    vectors = None
    if nearest:
        import numpy as np

        matrices = []
        for info in data["episodes"].values():
            directory = Path(info["directory"])
            if digest(directory / "segments.json") != info["segments_sha256"]:
                raise ValueError("原分组与当前片段不一致")
            own_records, own_vectors = load_embeddings(directory, data["model"])
            records.extend(own_records)
            matrices.append(own_vectors)
        vectors = np.concatenate(matrices)
        by_id = {r["id"]: r for r in data["assignments"]}
        if any(any(by_id[r["id"]][k] != v for k, v in r.items()) for r in records):
            raise ValueError("声纹片段与原分组不一致")
    matched, unmatched, special = match_annotations(data, annotations)
    assigned = {r["id"] for r in data["assignments"] if r["speaker"] is not None}
    by_role: dict[str, list[str]] = defaultdict(list)
    for clip_id, name in matched.items():
        if clip_id in assigned:
            by_role[name].append(clip_id)
    if not roles or len(set(roles)) != len(roles):
        raise ValueError("需要不重复的参考角色名")
    if any(len(by_role[name]) < 4 for name in roles):
        raise ValueError("每个参考角色至少需要 4 条标签，以留下至少 2 条评分片段")
    results = []
    candidate = None
    with TemporaryDirectory(prefix="avs-references-") as temp:
        for count in (1, 2):
            for seed in range(20):
                rng = random.Random(seed)
                support = {
                    clip_id: name
                    for name in sorted(roles)
                    for clip_id in rng.sample(sorted(by_role[name]), count)
                }
                baseline = evaluate(groups_file, annotations, set(support))
                for threshold in [0.3, 0.4, 0.5, 0.6] if nearest else [0.0]:
                    linked = (
                        assign_from_references(data, support, records, vectors, threshold)
                        if nearest
                        else link_reference_groups(data, support)
                    )
                    linked["support"]["base_groups_sha256"] = digest(groups_file)
                    path = Path(temp) / "candidate.json"
                    write_json(path, linked)
                    scored = evaluate(path, annotations)
                    if baseline["metrics"]["labeled_clips"] != scored["metrics"]["labeled_clips"]:
                        raise ValueError("参考方法与基线的评分片段不一致")
                    results.append(
                        {
                            "method": linked["strategy"],
                            "distance_threshold": threshold if nearest else None,
                            "references_per_role": count,
                            "seed": seed,
                            "support": support,
                            "baseline": baseline["metrics"],
                            "with_references": scored["metrics"],
                            "groups": linked["summary"]["groups"],
                            "roles": scored["roles"],
                        }
                    )
                    if count == 2 and seed == 0 and threshold == (0.5 if nearest else 0.0):
                        candidate = linked
    report = {
        "schema": "avs.reference_experiment.v1",
        "base_groups": str(groups_file.resolve()),
        "base_groups_sha256": digest(groups_file),
        "annotations": [{"path": str(p.resolve()), "sha256": digest(p)} for p in annotations],
        "reference_roles": roles,
        "unmatched_labels": unmatched,
        "special_labels": special,
        "results": results,
        "candidate": "candidate.json",
        "candidate_selection": "固定每人 2 条、种子 0；最近参考法用 0.5，不按评分选优。",
        "note": "同批旧标签上的参考合组实验；参考全部排除评分。重复划分相关，非新集独立检验。",
    }
    write_json(out / "report.json", report)
    write_json(out / "candidate.json", candidate)
    write_json(out / "candidate-evaluation.json", evaluate(out / "candidate.json", annotations))
    return report
