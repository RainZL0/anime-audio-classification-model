"""量成绩随片段池变大怎么变，并检验按池子定分界线能不能把它稳住。

做法：**被打分的那一集始终整集在池子里**，只往池子里加别的集的片段，加多少条由参数给。
这样每一档池子大小面对的是同一批人工标签、同一批配对，成绩可以直接比。加进来的片段随机抽，
每档抽好几遍，免得把一次抽样的运气当成规律。

报告里同时给两条线：

- **固定分界线**：每一档都用同一个数，也就是现在的做法。
- **按池子定分界线**：分界线由这个池子自己的距离算出来（见 stages/cluster.py 的 pool_threshold）。

判断哪条线更好，看的不是连上多少对，而是**错误合并稳不稳**。固定分界线的问题正是错误合并
会随池子变大一路往下掉：这不是变准了，是合并越来越保守，同一角色的片段也连不上了。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from avs.embeddings.extract import ANIME_VA, DEFAULT_THRESHOLDS
from avs.evaluation.identity import pair_counts
from avs.pipeline import load_embeddings
from avs.project import digest, load_episode, read_json, time_key, write_json
from avs.stages.cluster import POOL_MULTIPLIERS, POOL_QUANTILE, pool_threshold

SEEDS = 8
"""每一档池子大小抽几遍。抽样的运气不小，一遍看不出规律。"""


def _truth(directories: list[Path], scored: str, annotations: list[Path]) -> dict[str, str]:
    """被打分那一集的人工身份：片段 ID 到角色名。只收时间毫秒级精确对上的。"""
    episodes = {}
    for directory in directories:
        episode, rows = load_episode(directory)
        source = str(Path(episode["vocals"])).replace("\\", "/").rsplit("/", 1)[-1]
        episodes[source] = (episode["name"], {time_key(r): r["id"] for r in rows})
    matched: dict[str, str] = {}
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in episodes:
            raise ValueError(f"{path} 的音轨不在这些集目录里")
        name, by_time = episodes[source]
        if name != scored:
            continue
        for clip in annotation["clips"]:
            person = clip.get("name")
            if not person or person.startswith("__"):
                continue
            clip_id = by_time.get(time_key(clip))
            if clip_id is not None:
                matched[clip_id] = person
    if not matched:
        raise ValueError(f"这些人工归档里没有 {scored} 的名字，无法打分")
    return matched


def _sizes(total: int, steps: int) -> list[int]:
    """从「一条不加」到「全部加上」均匀取几档。"""
    if steps < 2:
        raise ValueError("至少要两档池子大小")
    marks = sorted({round(total * i / (steps - 1)) for i in range(steps)})
    return marks


def drift(
    episodes: list[Path],
    scored: str,
    annotations: list[Path],
    out: Path,
    model: str = ANIME_VA,
    threshold: float | None = None,
    multiplier: float | None = None,
    quantile: float = POOL_QUANTILE,
    steps: int = 7,
    seeds: int = SEEDS,
) -> dict[str, Any]:
    """扫池子大小，报固定分界线和按池子定分界线两条线的成绩。"""
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    if out.exists():
        raise ValueError(f"报告已存在：{out}")
    if len({p.resolve() for p in episodes}) != len(episodes):
        raise ValueError("集目录不能重复")
    threshold = DEFAULT_THRESHOLDS[model] if threshold is None else threshold
    multiplier = POOL_MULTIPLIERS[model] if multiplier is None else multiplier

    truth = _truth(episodes, scored, annotations)
    base: list[tuple[str, Any]] = []
    others: list[tuple[str, Any]] = []
    inputs = []
    for directory in episodes:
        episode, _ = load_episode(directory)
        records, vectors = load_embeddings(directory, model)
        target = base if episode["name"] == scored else others
        target.extend((row["id"], vector) for row, vector in zip(records, vectors, strict=True))
        inputs.append(
            {
                "episode": episode["name"],
                "directory": str(directory.resolve()),
                "segments_sha256": digest(directory / "segments.json"),
            }
        )
    if not base:
        raise ValueError(f"{scored} 不在这些集目录里")

    scored_ids = sorted(truth)
    names = [truth[i] for i in scored_ids]
    # 分界线扫得比 0.01 更细没有意义：漂移量本身就在 0.03 到 0.08 这个尺度上。
    grid = [round(0.45 + 0.01 * i, 3) for i in range(51)]

    def score(labels: dict[str, int]) -> tuple[int, int, int]:
        # 没进这个池子的片段各自算一组，跟 evaluate 对没有分到组的片段的处理一致。
        groups = [str(labels.get(i, f"solo:{i}")) for i in scored_ids]
        return pair_counts(names, groups)

    runs = []
    for extra in _sizes(len(others), steps):
        picks = [0] if extra in (0, len(others)) else list(range(seeds))
        for seed in picks:
            if extra == 0:
                added: list[tuple[str, Any]] = []
            elif extra == len(others):
                added = others
            else:
                chosen = np.random.default_rng(1000 * seed + extra).choice(
                    len(others), extra, replace=False
                )
                added = [others[i] for i in chosen]
            pool = base + added
            ids = [p[0] for p in pool]
            vectors = np.stack([p[1] for p in pool])
            distances = pdist(vectors, metric="cosine")
            tree = linkage(distances, method="average")
            relative = pool_threshold(vectors, multiplier, quantile)
            others_stats = _other_statistics(vectors, distances, tree)
            curve = []
            for cut in grid:
                hits, false_merges, missed = score(
                    dict(zip(ids, fcluster(tree, cut, criterion="distance").tolist(), strict=True))
                )
                curve.append(
                    {
                        "threshold": cut,
                        "correct_same_person_pairs": hits,
                        "false_merged_pairs": false_merges,
                        "missed_same_person_pairs": missed,
                    }
                )
            runs.append(
                {
                    "pool_clips": len(pool),
                    "added_clips": extra,
                    "seed": seed,
                    "pool_quantile_distance": round(relative / multiplier, 4),
                    "relative_threshold": round(relative, 4),
                    "other_pool_statistics": others_stats,
                    "curve": curve,
                }
            )

    report = {
        "schema": "avs.drift.v1",
        "note": "被打分的那一集始终整集在池子里，加进来的是别的集的片段；同一批标签、同一批配对。",
        "model": model,
        "scored_episode": scored,
        "labeled_clips": len(truth),
        "roles": len(set(truth.values())),
        "fixed_threshold": threshold,
        "pool_quantile": quantile,
        "pool_multiplier": multiplier,
        "seeds_per_size": seeds,
        "inputs": inputs,
        "annotations": [{"path": str(p.resolve()), "sha256": digest(p)} for p in annotations],
        "summary": _summary(runs, threshold),
        "runs": runs,
    }
    write_json(out, report)
    return report


def _other_statistics(vectors: Any, distances: Any, tree: Any) -> dict[str, float]:
    """几个也能不看标签就从池子里算出来的量，记下来供核对。

    这些都试过，没有一个能当分界线用：分界线需要随池子变大往外挪 4% 到 11%，
    而配对距离的中位数几乎不动（池子里绝大多数配对本来就是不同角色），
    最近邻距离和合并高度反而随池子变大往里缩，方向正好相反。留着是为了不用重做一遍才知道。
    """
    import numpy as np

    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -np.inf)
    nearest = 1 - similarity.max(axis=1)
    return {
        "pair_distance_q05": round(float(np.quantile(distances, 0.05)), 4),
        "pair_distance_median": round(float(np.median(distances)), 4),
        "nearest_neighbour_distance_median": round(float(np.median(nearest)), 4),
        "merge_height_median": round(float(np.median(tree[:, 2])), 4),
    }


def _summary(runs: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """每一档池子大小一行，两条线并排。数字是同一档各次抽样的平均。"""
    import numpy as np

    rows = []
    for pool in sorted({r["pool_clips"] for r in runs}):
        same = [r for r in runs if r["pool_clips"] == pool]
        fixed = [_at(r["curve"], threshold) for r in same]
        relative = [_at(r["curve"], r["relative_threshold"]) for r in same]

        def mean(points: list[dict[str, Any]], key: str) -> float:
            return round(float(np.mean([p[key] for p in points])), 1)

        rows.append(
            {
                "pool_clips": pool,
                "samples": len(same),
                "fixed_threshold": threshold,
                "fixed_correct_pairs": mean(fixed, "correct_same_person_pairs"),
                "fixed_false_merges": mean(fixed, "false_merged_pairs"),
                "relative_threshold": round(
                    float(np.mean([r["relative_threshold"] for r in same])), 4
                ),
                "relative_correct_pairs": mean(relative, "correct_same_person_pairs"),
                "relative_false_merges": mean(relative, "false_merged_pairs"),
            }
        )
    return rows


def _at(curve: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """扫的是一格一格的分界线，取离要问的那个数最近的一格。"""
    return min(curve, key=lambda point: abs(point["threshold"] - threshold))
