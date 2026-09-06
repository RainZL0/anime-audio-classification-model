"""只评价说话人身份：精确时间匹配、错误合并、该合没合和每角色散成很多小组数。"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from avs.project import read_json, time_key


def pair_counts(truth: list[str], predicted: list[Any]) -> tuple[int, int, int]:
    """数出连上、错误合并、该合没合三个配对数。

    按人工名字乘机器组号的计数表算，不逐对循环：扫分界线时同一批标签要数上千遍，
    逐对循环慢到不能用，而两种算法的结果完全一样。
    """
    import numpy as np

    if len(truth) != len(predicted):
        raise ValueError("人工标签和预测长度不同")
    _, names = np.unique(np.asarray(truth, dtype=str), return_inverse=True)
    _, groups = np.unique(np.asarray(predicted, dtype=str), return_inverse=True)
    table = np.zeros((names.max(initial=-1) + 1, groups.max(initial=-1) + 1), dtype=np.int64)
    np.add.at(table, (names, groups), 1)

    def pairs(counts: Any) -> int:
        return int((counts * (counts - 1) // 2).sum())

    hits = pairs(table)
    return hits, pairs(table.sum(axis=0)) - hits, pairs(table.sum(axis=1)) - hits


def identity_metrics(truth: list[str], predicted: list[int]) -> dict[str, Any]:
    """同时报错误合并与该合没合，防止把每条独立成组伪装成完美识别。"""
    from sklearn.metrics import adjusted_rand_score

    hits, false_merges, missed_links = pair_counts(truth, predicted)
    groups: dict[int, list[str]] = defaultdict(list)
    for name, label in zip(truth, predicted, strict=True):
        groups[label].append(name)
    purity_hits = sum(Counter(names).most_common(1)[0][1] for names in groups.values())
    return {
        "labeled_clips": len(truth),
        "roles": len(set(truth)),
        "correct_same_person_pairs": hits,
        "false_merged_pairs": false_merges,
        "missed_same_person_pairs": missed_links,
        "pair_precision": round(hits / (hits + false_merges), 4) if hits + false_merges else None,
        "pair_recall": round(hits / (hits + missed_links), 4) if hits + missed_links else None,
        "sample_purity": round(purity_hits / len(truth), 4) if truth else None,
        "adjusted_rand": round(float(adjusted_rand_score(truth, predicted)), 4)
        if len(truth) >= 2
        else None,
    }


def episode_by_source(data: dict[str, Any]) -> dict[str, str]:
    """人声文件名到集名的映射；人工归档只记了音轨文件，靠它找回是哪一集。"""
    if data.get("schema") != "avs.groups.v1":
        raise ValueError("不是当前分组文件")
    sources: dict[str, str] = {}
    for episode, info in data["episodes"].items():
        key = str(info["vocals"]).replace("\\", "/").rsplit("/", 1)[-1]
        if key in sources:
            raise ValueError("不同集使用同名人声文件，无法安全匹配旧标注")
        sources[key] = episode
    return sources


def annotated_clip_ids(data: dict[str, Any], annotations: list[Path]) -> set[str]:
    """人工归档里已经出现过的片段，含特殊标签和留空的。用于不重复安排标注。"""
    sources = episode_by_source(data)
    by_time = {(r["episode"], time_key(r)): r["id"] for r in data["assignments"]}
    covered: set[str] = set()
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"{path} 的音轨不在此次分组中")
        for clip in annotation["clips"]:
            clip_id = by_time.get((sources[source], time_key(clip)))
            if clip_id is not None:
                covered.add(clip_id)
    return covered


def match_annotations(
    data: dict[str, Any], annotations: list[Path]
) -> tuple[dict[str, str], int, int]:
    """只返回精确匹配的人工身份；供评估和参考样本划分共用。"""
    sources = episode_by_source(data)
    by_time = {(r["episode"], time_key(r)): r for r in data["assignments"]}
    matched: dict[str, str] = {}
    unmatched = special = 0
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"{path} 的音轨不在此次分组中")
        for clip in annotation["clips"]:
            name = clip.get("name")
            if not name:
                continue
            if name.startswith("__"):
                special += 1
                continue
            row = by_time.get((sources[source], time_key(clip)))
            if row is None:
                unmatched += 1
                continue
            if row["id"] in matched and matched[row["id"]] != name:
                raise ValueError("同一片段有冲突的人工身份标签")
            matched[row["id"]] = name
    return matched, unmatched, special


def evaluate(
    groups_file: Path, annotations: list[Path], exclude_ids: set[str] | None = None
) -> dict[str, Any]:
    """精确对照身份；参考片段自动排除，额外排除用于公平的基线对照。"""
    data = read_json(groups_file)
    matched, unmatched, special = match_annotations(data, annotations)
    excluded = set(data.get("support", {}).get("clip_ids", [])) | (exclude_ids or set())
    excluded_labels = len(excluded & matched.keys())
    matched = {key: name for key, name in matched.items() if key not in excluded}
    unassigned = 0
    truth = []
    predicted = []
    role_groups: dict[str, set[str]] = defaultdict(set)
    role_seconds: dict[str, float] = defaultdict(float)
    numbers: dict[str, int] = {}
    for row in data["assignments"]:
        name = matched.get(row["id"])
        if name is None:
            continue
        group = row["speaker"]
        if group is None:
            unassigned += 1
            group = f"unassigned:{row['id']}"
        else:
            role_groups[name].add(group)
            role_seconds[name] += row["end"] - row["start"]
        truth.append(name)
        predicted.append(numbers.setdefault(group, len(numbers)))
    return {
        "groups_file": str(groups_file.resolve()),
        "metrics": identity_metrics(truth, predicted),
        "unmatched_labels": unmatched,
        "special_labels": special,
        "labeled_unassigned": unassigned,
        "excluded_support_labels": excluded_labels,
        "roles": {
            name: {
                "groups": len(role_groups[name]),
                "labeled_assigned_seconds": round(role_seconds[name], 3),
            }
            for name in sorted(set(truth))
        },
        "note": "只评价已标注且时间精确对应的片段；同批调参结果不是独立验证。",
    }
