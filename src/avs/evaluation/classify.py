"""按集留出检验：在别的集的人工标签上训练，把被测那一集的片段直接分到角色名下。

三种做法并排比，全部只用缓存的声纹，不重算：

- **最像的一条**：跟训练集里最像的那一条已标片段同名。分组靠的就是这种一条比一条。
- **角色平均**：每个角色的已标片段平均成一个方向，片段归给最近的那个角色。
- **小分类器**：在训练集声纹上训练的逻辑回归。正则强度只在训练集内部按集交叉验证挑，
  不看被测集。

每条预测附带把握大小，按把握从高到低排，报前 50%、前 80% 和全部片段的正确率。
被测集里有、训练集里没有的角色一定判错，照样算进分母，另报它们有多少条。
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

from avs.pipeline import load_embeddings
from avs.project import load_episode, read_json, time_key, write_json

DURATION_BINS = ((0.5, 1.0), (1.0, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, math.inf))
COVERAGES = (0.5, 0.8, 1.0)
STRENGTHS = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
"""逻辑回归正则强度的候选，数越大约束越松。只在训练集内部挑。"""

METHODS = ("nearest", "centroid", "logistic")


def labels_by_episode(
    directories: list[Path], annotations: list[Path]
) -> dict[str, dict[str, str]]:
    """每一集的人工身份：集名到「片段 ID 到角色名」。只收时间毫秒级精确对上的，特殊标签不收。"""
    episodes = {}
    for directory in directories:
        episode, rows = load_episode(directory)
        source = str(Path(episode["vocals"])).replace("\\", "/").rsplit("/", 1)[-1]
        episodes[source] = (episode["name"], {time_key(r): r["id"] for r in rows})
    found: dict[str, dict[str, str]] = {name: {} for name, _ in episodes.values()}
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in episodes:
            raise ValueError(f"{path} 的音轨不在这些集目录里")
        name, by_time = episodes[source]
        for clip in annotation["clips"]:
            person = clip.get("name")
            if not person or person.startswith("__"):
                continue
            clip_id = by_time.get(time_key(clip))
            if clip_id is None:
                continue
            if found[name].get(clip_id, person) != person:
                raise ValueError("同一片段有冲突的人工身份标签")
            found[name][clip_id] = person
    return found


def features(directory: Path, models: list[str]) -> tuple[list[dict[str, Any]], Any]:
    """一集的声纹。多个模型时各自是单位长度，按片段 ID 对齐后拼起来，再整体归一。"""
    import numpy as np

    base: list[dict[str, Any]] = []
    parts = []
    for model in models:
        records, vectors = load_embeddings(directory, model)
        order = {r["id"]: i for i, r in enumerate(records)}
        if not base:
            base = records
        elif set(order) != {r["id"] for r in base}:
            raise ValueError("模型覆盖的片段不同，不能拼在一起")
        parts.append(vectors[[order[r["id"]] for r in base]])
    joined = np.concatenate(parts, axis=1)
    return base, joined / np.linalg.norm(joined, axis=1, keepdims=True)


def _class_scores(method: str, train: Any, names: list[str], test: Any, strength: float) -> Any:
    """返回（角色名列表, 每条测试片段对每个角色的分数）。分数越大越像。"""
    import numpy as np

    roles = sorted(set(names))
    index = np.array([roles.index(n) for n in names])
    if method == "nearest":
        similarity = test @ train.T
        scores = np.full((len(test), len(roles)), -np.inf)
        for k in range(len(roles)):
            scores[:, k] = similarity[:, index == k].max(axis=1)
        return roles, scores
    if method == "centroid":
        centers = np.stack([train[index == k].mean(axis=0) for k in range(len(roles))])
        centers /= np.linalg.norm(centers, axis=1, keepdims=True)
        return roles, test @ centers.T
    if method == "logistic":
        from sklearn.linear_model import LogisticRegression

        if len(roles) == 1:
            return roles, np.ones((len(test), 1))
        model = LogisticRegression(C=strength, max_iter=5000)
        model.fit(train, index)
        return [roles[k] for k in model.classes_], model.predict_proba(test)
    raise ValueError(f"不认识的做法 {method!r}")


def predict(
    method: str, train: Any, names: list[str], test: Any, strength: float = 10.0
) -> tuple[list[str], list[float]]:
    """每条测试片段的预测角色和把握大小。

    逻辑回归的把握是它给的概率；另两种是第一名比第二名高出多少，只有一个角色时记 1。
    """
    import numpy as np

    roles, scores = _class_scores(method, train, names, test, strength)
    order = np.argsort(-scores, axis=1)
    top = scores[np.arange(len(test)), order[:, 0]]
    if method == "logistic":
        confidence = top
    elif len(roles) > 1:
        confidence = top - scores[np.arange(len(test)), order[:, 1]]
    else:
        confidence = np.ones(len(test))
    return [roles[k] for k in order[:, 0]], [float(c) for c in confidence]


def pick_strength(pool: dict[str, tuple[Any, list[str]]]) -> tuple[float, dict[str, float]]:
    """在训练集内部按集轮流留出，挑逻辑回归的正则强度。只有一集训练时用中间值。"""
    import numpy as np

    if len(pool) < 2:
        return 10.0, {}
    results: dict[str, float] = {}
    for strength in STRENGTHS:
        right = total = 0
        for held in pool:
            train = np.concatenate([v for e, (v, _) in pool.items() if e != held])
            names = [n for e, (_, ns) in pool.items() if e != held for n in ns]
            guesses, _ = predict("logistic", train, names, pool[held][0], strength)
            right += sum(g == t for g, t in zip(guesses, pool[held][1], strict=True))
            total += len(guesses)
        results[f"{strength:g}"] = round(right / total, 4)
    best = max(STRENGTHS, key=lambda s: (results[f"{s:g}"], -s))
    return best, results


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def summarize(
    truth: list[str], guesses: list[str], confidence: list[float], durations: list[float]
) -> dict[str, Any]:
    """正确率：全部、按时长分档、按把握从高到低取前若干比例。"""
    right = [g == t for g, t in zip(guesses, truth, strict=True)]
    by_duration = {}
    for low, high in DURATION_BINS:
        inside = [r for r, d in zip(right, durations, strict=True) if low <= d < high]
        label = f"{low:g}-{high:g}s" if math.isfinite(high) else f">={low:g}s"
        by_duration[label] = {"clips": len(inside), "accuracy": _rate(inside)}
    ranked = [r for _, r in sorted(zip(confidence, right, strict=True), key=lambda p: -p[0])]
    by_coverage = {
        f"top{round(share * 100)}%": _rate(ranked[: max(1, math.ceil(share * len(ranked)))])
        for share in COVERAGES
    }
    return {"accuracy": _rate(right), "by_duration": by_duration, "by_confidence": by_coverage}


def classify_check(
    directories: list[Path],
    test: str,
    annotations: list[Path],
    out: Path,
    models: list[str],
) -> dict[str, Any]:
    """训练用除 `test` 以外各集的人工标签，只在 `test` 那一集上打分。"""
    import numpy as np

    if out.exists():
        raise ValueError(f"{out} 已存在，换一个文件名")
    labels = labels_by_episode(directories, annotations)
    if not labels.get(test):
        raise ValueError(f"这些人工归档里没有 {test} 的名字，无法打分")

    pool: dict[str, tuple[Any, list[str]]] = {}
    held: tuple[list[dict[str, Any]], Any, list[str]] | None = None
    for directory in directories:
        episode, _ = load_episode(directory)
        records, vectors = features(directory, models)
        own = labels[episode["name"]]
        keep = [i for i, r in enumerate(records) if r["id"] in own]
        names = [own[records[i]["id"]] for i in keep]
        if episode["name"] == test:
            held = ([records[i] for i in keep], vectors[keep], names)
        elif keep:
            pool[episode["name"]] = (vectors[keep], names)
    if held is None or not pool:
        raise ValueError("需要被测的那一集，以及至少一集有标签的训练集")

    records, test_vectors, truth = held
    train = np.concatenate([v for v, _ in pool.values()])
    train_names = [n for _, ns in pool.values() for n in ns]
    durations = [float(r["end"] - r["start"]) for r in records]
    seen = set(train_names)
    strength, search = pick_strength(pool)

    results = {}
    per_clip: dict[str, list[dict[str, Any]]] = {}
    for method in METHODS:
        guesses, confidence = predict(method, train, train_names, test_vectors, strength)
        results[method] = summarize(truth, guesses, confidence, durations)
        per_clip[method] = [
            {
                "id": r["id"],
                "start": r["start"],
                "end": r["end"],
                "truth": t,
                "predicted": g,
                "confidence": round(c, 4),
            }
            for r, t, g, c in zip(records, truth, guesses, confidence, strict=True)
        ]

    report = {
        "schema": "avs.classify-check.v1",
        "models": models,
        "train_episodes": {e: len(ns) for e, (_, ns) in pool.items()},
        "test_episode": test,
        "test_clips": len(truth),
        "train_roles": len(seen),
        "test_roles": len(set(truth)),
        "unseen_role_clips": sum(t not in seen for t in truth),
        "unseen_roles": dict(Counter(t for t in truth if t not in seen)),
        "logistic_strength": strength,
        "logistic_strength_search": search,
        "results": results,
        "clips": per_clip,
        "note": "短于 0.5 秒的片段没有声纹，不在其中；训练集没有的角色照样算判错。",
    }
    write_json(out, report)
    return report
