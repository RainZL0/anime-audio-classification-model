"""Measure how the scores change as the clip pool grows, and test whether setting the threshold from
the pool keeps them steady.

Method: **the scored episode always stays in the pool in full**, and only clips from other episodes
are added. The number of clips added is set by a parameter. This way every pool size faces the same
human labels and the same pairs, so the scores can be compared directly. The added clips are picked
at random, and each size is run several times, so that one lucky draw is not mistaken for a pattern.

The report gives two lines at once:

- **Fixed threshold**: the same number at every pool size. This is how it works now.
- **Pool-based threshold**: the threshold is computed from this pool's own distances (see
  pool_threshold in stages/cluster.py).

To judge which line is better, look not at how many pairs get linked, but at whether **wrong merges
stay stable**. The problem with the fixed threshold is exactly that wrong merges keep falling as the
pool grows. That is not the system becoming more accurate. Merging is just getting more
conservative, so clips of the same character stop getting linked too.
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
"""How many random draws to run for each pool size. Sampling luck is large, so one draw does not
show a pattern."""


def _truth(directories: list[Path], scored: str, annotations: list[Path]) -> dict[str, str]:
    """Human identities in the scored episode: clip ID to character name. Only collects labels whose
    time matches exactly to the millisecond."""
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
            raise ValueError(f"{path} has an audio track that is not in these episode folders")
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
        raise ValueError(f"No labels for {scored} in these human archives, so it cannot be scored")
    return matched


def _sizes(total: int, steps: int) -> list[int]:
    """Pick several evenly spaced sizes, from 'add nothing' to 'add everything'."""
    if steps < 2:
        raise ValueError("Need at least two pool sizes")
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
    """Scan pool sizes, and report the scores for both the fixed-threshold line and the
    pool-based-threshold line."""
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    if out.exists():
        raise ValueError(f"Report already exists: {out}")
    if len({p.resolve() for p in episodes}) != len(episodes):
        raise ValueError("Episode folders must not repeat")
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
        raise ValueError(f"{scored} is not in these episode folders")

    scored_ids = sorted(truth)
    names = [truth[i] for i in scored_ids]
    # Scanning the threshold finer than 0.01 is pointless: the drift itself is on the scale of 0.03
    # to 0.08.
    grid = [round(0.45 + 0.01 * i, 3) for i in range(51)]

    def score(labels: dict[str, int]) -> tuple[int, int, int]:
        # Clips that are not in this pool each count as their own group. This matches how evaluate
        # treats clips that were not assigned to a group.
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
        "note": "The scored episode always stays in the pool in full. "
        "The clips added are from other episodes. Same labels, same pairs.",
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
    """A few quantities that can also be computed from the pool without using labels. They are
    recorded here for checking.

    All of these were tried, and none can be used as a threshold. The threshold would need to move
    outward by 4% to 11% as the pool grows. But the median pair distance hardly moves, because most
    pairs in the pool are already between different characters. And the nearest-neighbour distance
    and the merge height shrink inward as the pool grows, which is the opposite direction. They are
    kept so that the check does not have to be redone to find this out.
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
    """One row per pool size, with the two lines side by side. The numbers are the average of the
    draws at that size."""
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
    """The scan goes in steps, so take the step closest to the threshold asked for."""
    return min(curve, key=lambda point: abs(point["threshold"] - threshold))
