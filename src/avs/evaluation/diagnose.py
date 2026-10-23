"""Diagnose whether identities can be told apart, using fixed clips, human labels, and cached
voiceprints. This only locates evidence; it does not pick a method.

Nearest-neighbor search (finding the closest other clip) leaves out the query clip itself. A role
with only one label is not used as a query, but it stays in the candidate pool as a distractor.
A nearest neighbor that is unlabeled is only treated as a clue, not as a wrong match. The two
models use exactly the same candidate pool.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from avs.evaluation.identity import match_annotations
from avs.pipeline import load_embeddings
from avs.project import digest, load_episode, read_json, write_json

DURATION_BINS = ((0.0, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, math.inf))
TOP_KS = (1, 3, 5)
EXAMPLES_PER_KIND = 8


def duration_bin(seconds: float) -> str:
    for low, high in DURATION_BINS:
        if low <= seconds < high:
            return f"{low:g}-{high:g}s" if math.isfinite(high) else f">={low:g}s"
    raise ValueError("Clip duration must be a non-negative finite number")


def load_pool(
    episodes: list[Path], models: list[str], window: float = 0.0
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """All models must cover the same set of clips. Each model's matrix is aligned to the same row
    order by clip ID."""
    import numpy as np

    if not models or len(set(models)) != len(models):
        raise ValueError("Need model names that are not repeated")
    if not episodes or len({p.resolve() for p in episodes}) != len(episodes):
        raise ValueError("Need at least one episode folder, with no repeats")
    info: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    parts: dict[str, list[Any]] = defaultdict(list)
    for directory in episodes:
        episode, _ = load_episode(directory)
        if episode["name"] in info:
            raise ValueError("Episode names repeat. Use a different name for each episode")
        info[episode["name"]] = {
            "vocals": episode["vocals"],
            "directory": str(directory.resolve()),
            "segments_sha256": digest(directory / "segments.json"),
        }
        base: list[dict[str, Any]] = []
        for model in models:
            own, vectors = load_embeddings(directory, model, window)
            order = {r["id"]: i for i, r in enumerate(own)}
            if model == models[0]:
                base = own
            elif set(order) != {r["id"] for r in base}:
                raise ValueError(
                    "Models cover different clips, so they cannot be compared directly"
                )
            parts[model].append(vectors[[order[r["id"]] for r in base]])
        records.extend(base)
    vectors = {m: np.concatenate(parts[m]) if parts[m] else np.empty((0, 0)) for m in models}
    return info, records, vectors


def _quantiles(values: Any) -> dict[str, float | None] | None:
    import numpy as np

    if not len(values):
        return None
    points = np.quantile(values, [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1])
    return dict(
        zip(
            ["min", "p10", "p25", "p50", "p75", "p90", "max"],
            (round(float(v), 4) for v in points),
            strict=True,
        )
    )


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def analyse(
    vectors: Any,
    records: list[dict[str, Any]],
    labeled: list[int],
    names: list[str],
    groups: dict[str, str | None] | None,
    threshold: float,
) -> dict[str, Any]:
    """Per-query nearest neighbors, pair distances, and breakdowns by duration and role for one
    model."""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    n = len(labeled)
    sub = vectors[labeled]
    dist = 1 - sub @ sub.T
    np.fill_diagonal(dist, np.inf)
    roles = np.array(names)
    episodes = np.array([records[i]["episode"] for i in labeled])
    durations = [float(records[i]["end"] - records[i]["start"]) for i in labeled]
    counts = Counter(names)
    position = {row: k for k, row in enumerate(labeled)}
    full = 1 - vectors @ sub.T
    full[labeled, np.arange(n)] = np.inf

    def clip(k: int) -> dict[str, Any]:
        row = records[labeled[k]]
        return {
            "id": row["id"],
            "episode": row["episode"],
            "start": row["start"],
            "end": row["end"],
            "duration": round(durations[k], 3),
            "role": names[k],
            "group": groups.get(row["id"]) if groups else None,
        }

    queries: list[dict[str, Any]] = []
    for q in range(n):
        if counts[names[q]] < 2:
            continue
        row = dist[q]
        order = np.argsort(row, kind="stable")
        same = roles == names[q]
        same[q] = False
        other = ~same
        other[q] = False
        nearest_same = int(np.argmin(np.where(same, row, np.inf)))
        nearest_other = int(np.argmin(np.where(other, row, np.inf)))
        scoped: dict[str, bool | None] = {}
        for scope, pool in (
            ("same_episode", episodes == episodes[q]),
            ("cross_episode", episodes != episodes[q]),
        ):
            pool = pool.copy()
            pool[q] = False
            scoped[scope] = (
                bool(same[int(np.argmin(np.where(pool, row, np.inf)))])
                if (pool & same).any()
                else None
            )
        best_all = int(np.argmin(full[:, q]))
        if best_all in position:
            status = "same_role" if names[position[best_all]] == names[q] else "other_role"
        else:
            status = "unlabeled"
        top1 = int(order[0])
        queries.append(
            {
                **clip(q),
                "duration_bin": duration_bin(durations[q]),
                "top1": {**clip(top1), "distance": round(float(row[top1]), 4)},
                **{f"top{k}_same_role": bool(same[order[:k]].any()) for k in TOP_KS},
                "nearest_same_role": {
                    "id": records[labeled[nearest_same]]["id"],
                    "distance": round(float(row[nearest_same]), 4),
                },
                "nearest_other_role": {
                    "id": records[labeled[nearest_other]]["id"],
                    "role": names[nearest_other],
                    "distance": round(float(row[nearest_other]), 4),
                },
                "margin": round(float(row[nearest_same] - row[nearest_other]), 4),
                **{f"{scope}_top1_same_role": hit for scope, hit in scoped.items()},
                "top1_in_same_group": (
                    groups.get(records[labeled[q]]["id"])
                    == groups.get(records[labeled[top1]]["id"])
                    if groups
                    else None
                ),
                "full_pool_top1": {
                    "id": records[best_all]["id"],
                    "status": status,
                    "distance": round(float(full[best_all, q]), 4),
                },
            }
        )

    per_role: dict[str, dict[str, Any]] = {}
    for role in sorted(counts):
        own = [x for x in queries if x["role"] == role]
        per_role[role] = {
            "labeled": counts[role],
            "queries": len(own),
            **{f"top{k}_hit_rate": _rate([x[f"top{k}_same_role"] for x in own]) for k in TOP_KS},
            **{
                f"median_nearest_{kind}_role": round(
                    float(np.median([x[f"nearest_{kind}_role"]["distance"] for x in own])), 4
                )
                if own
                else None
                for kind in ("same", "other")
            },
        }
    role_rates = [r["top1_hit_rate"] for r in per_role.values() if r["top1_hit_rate"] is not None]
    bins = {}
    for label in (duration_bin(x) for x in (0.0, 1.5, 3.0, 6.0)):
        own = [x for x in queries if x["duration_bin"] == label]
        bins[label] = {
            "queries": len(own),
            "top1_hit_rate": _rate([x["top1_same_role"] for x in own]),
        }
    retrieval = {
        "queries": len(queries),
        **{f"top{k}_hit_rate": _rate([x[f"top{k}_same_role"] for x in queries]) for k in TOP_KS},
        "macro_top1_hit_rate": round(sum(role_rates) / len(role_rates), 4) if role_rates else None,
        "wrong_top1_in_same_group": sum(
            1 for x in queries if not x["top1_same_role"] and x["top1_in_same_group"]
        )
        if groups
        else None,
        **{
            scope: {
                "evaluable": sum(x[f"{scope}_top1_same_role"] is not None for x in queries),
                "top1_hit_rate": _rate(
                    [
                        x[f"{scope}_top1_same_role"]
                        for x in queries
                        if x[f"{scope}_top1_same_role"] is not None
                    ]
                ),
            }
            for scope in ("same_episode", "cross_episode")
        },
        "by_duration": bins,
        "full_pool_top1": dict(Counter(x["full_pool_top1"]["status"] for x in queries)),
        "roles": per_role,
    }

    upper = np.triu_indices(n, 1)
    d = dist[upper]
    same_pair = roles[upper[0]] == roles[upper[1]]
    same_d, other_d = np.sort(d[same_pair]), np.sort(d[~same_pair])
    crossing = None
    if len(same_d) and len(other_d):
        best = None
        for t in np.unique(d):
            miss = 1 - np.searchsorted(same_d, t, "right") / len(same_d)
            false = np.searchsorted(other_d, t, "right") / len(other_d)
            if best is None or abs(miss - false) < best[0]:
                best = (abs(miss - false), float(t), float(miss), float(false))
        assert best is not None
        crossing = {
            "distance": round(best[1], 4),
            "same_role_above": round(best[2], 4),
            "other_role_below": round(best[3], 4),
        }
    pair_bins: dict[str, dict[str, Any]] = {}
    for label in bins:
        chosen = [
            k
            for k, (i, j) in enumerate(zip(*upper, strict=True))
            if same_pair[k] and duration_bin(min(durations[i], durations[j])) == label
        ]
        pair_bins[label] = {
            "same_role_pairs": len(chosen),
            "median_distance": round(float(np.median(d[chosen])), 4) if chosen else None,
            "above_threshold": _rate([bool(d[k] > threshold) for k in chosen]),
        }
    distances = {
        "threshold": threshold,
        "same_role_pairs": len(same_d),
        "other_role_pairs": len(other_d),
        "same_role": _quantiles(same_d),
        "other_role": _quantiles(other_d),
        "pair_auc": round(float(roc_auc_score(same_pair, -d)), 4)
        if len(same_d) and len(other_d)
        else None,
        "same_role_above_threshold": _rate([bool(x > threshold) for x in same_d]),
        "other_role_below_threshold": _rate([bool(x <= threshold) for x in other_d]),
        "equal_error_point": crossing,
        "same_role_by_min_duration": pair_bins,
    }
    pairs: list[dict[str, Any]] = [
        {
            "a": records[labeled[i]]["id"],
            "b": records[labeled[j]]["id"],
            "same_role": bool(same_pair[k]),
            "distance": round(float(d[k]), 4),
            "same_group": (
                groups.get(records[labeled[i]]["id"]) == groups.get(records[labeled[j]]["id"])
                if groups
                else None
            ),
        }
        for k, (i, j) in enumerate(zip(*upper, strict=True))
    ]
    grouping = None
    if groups:
        missed = [p["distance"] for p in pairs if p["same_role"] and not p["same_group"]]
        linked = [p["distance"] for p in pairs if p["same_role"] and p["same_group"]]
        merged = [p["distance"] for p in pairs if not p["same_role"] and p["same_group"]]
        grouping = {
            "missed_same_role_pairs": len(missed),
            "missed_within_threshold": sum(x <= threshold for x in missed),
            "missed_distance": _quantiles(missed),
            "linked_distance": _quantiles(linked),
            "false_merged_pairs": len(merged),
            "false_merged_distance": _quantiles(merged),
        }
    return {
        "retrieval": retrieval,
        "distances": distances,
        "grouping": grouping,
        "queries": queries,
        "pairs": pairs,
    }


def select_examples(
    result: dict[str, Any],
    records: list[dict[str, Any]],
    matched: dict[str, str],
    groups: dict[str, str | None] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Pick error examples by a rule fixed in advance. Each clip appears at most once in each
    category."""
    by_id = {r["id"]: r for r in records}

    def clip(clip_id: str) -> dict[str, Any]:
        row = by_id[clip_id]
        return {
            "id": clip_id,
            "episode": row["episode"],
            "start": row["start"],
            "end": row["end"],
            "duration": round(float(row["end"] - row["start"]), 3),
            "role": matched[clip_id],
            "group": groups.get(clip_id) if groups else None,
        }

    def pick(candidates: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
        used: set[str] = set()
        chosen = []
        for a, b, distance in candidates:
            if a in used or b in used:
                continue
            used.update((a, b))
            chosen.append({"clips": [clip(a), clip(b)], "distance": distance})
            if len(chosen) == EXAMPLES_PER_KIND:
                break
        return chosen

    pairs = result["pairs"]
    same = sorted((p for p in pairs if p["same_role"]), key=lambda p: -p["distance"])
    other = sorted((p for p in pairs if not p["same_role"]), key=lambda p: p["distance"])
    wrong = sorted(
        (q for q in result["queries"] if not q["top1_same_role"]), key=lambda q: -q["margin"]
    )
    return {
        "far_same_role": pick([(p["a"], p["b"], p["distance"]) for p in same]),
        "near_other_role": pick([(p["a"], p["b"], p["distance"]) for p in other]),
        "wrong_top1": pick([(q["id"], q["top1"]["id"], q["top1"]["distance"]) for q in wrong]),
    }


def diagnose(
    episodes: list[Path],
    annotations: list[Path],
    models: list[str],
    out: Path,
    groups_file: Path | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Does not rerun the audio model or change the grouping. Outputs the report, per-pair
    distances, and error examples that can be listened to."""
    from avs.stages.export import export

    if out.exists():
        raise ValueError(f"Output directory already exists: {out}")
    info, records, vectors = load_pool(episodes, models)
    matched, unmatched, special = match_annotations(
        {"schema": "avs.groups.v1", "episodes": info, "assignments": records}, annotations
    )
    groups = None
    if groups_file is not None:
        data = read_json(groups_file)
        if data.get("schema") != "avs.groups.v1" or data.get("support"):
            raise ValueError(
                "Needs a grouping file made by the current group command, with no references used"
            )
        for name, own in info.items():
            if data["episodes"].get(name, {}).get("segments_sha256") != own["segments_sha256"]:
                raise ValueError("The grouping file does not match the current clips")
        by_id = {r["id"]: r["speaker"] for r in data["assignments"]}
        groups = {r["id"]: by_id[r["id"]] for r in records}
        threshold = float(data["threshold"])
    labeled = [i for i, r in enumerate(records) if r["id"] in matched]
    names = [matched[records[i]["id"]] for i in labeled]
    counts = Counter(names)
    if len(counts) < 2 or max(counts.values()) < 2:
        raise ValueError(
            "Need at least two characters, and at least one character with two or more "
            "labeled clips that have voiceprints"
        )
    results = {m: analyse(vectors[m], records, labeled, names, groups, threshold) for m in models}
    examples = select_examples(results[models[0]], records, matched, groups)
    distances = {m: {(p["a"], p["b"]): p["distance"] for p in results[m]["pairs"]} for m in models}
    assigned: dict[str, list[Any]] = {}
    for kind, items in examples.items():
        for index, item in enumerate(items, 1):
            a, b = (c["id"] for c in item["clips"])
            item["distances"] = {
                m: distances[m].get((a, b), distances[m].get((b, a))) for m in models
            }
            item["folder"] = f"examples/{kind}/{index:02d}"
            assigned[f"examples/{kind}/{index:02d}"] = [SimpleNamespace(**c) for c in item["clips"]]
    if assigned:
        export(assigned, {name: Path(own["vocals"]) for name, own in info.items()}, out)
    report = {
        "schema": "avs.embedding_diagnosis.v1",
        "note": "Diagnosis of fixed clips and the two models' caches. This only locates evidence. "
        "A nearest-neighbor failure does not prove that the vectors carry no identity "
        "information at all.",
        "inputs": [
            {
                "episode": own["directory"],
                "model": m,
                "segments_sha256": own["segments_sha256"],
                "vectors_sha256": digest(Path(own["directory"]) / "embeddings" / m / "vectors.npy"),
            }
            for own in info.values()
            for m in models
        ],
        "annotations": [{"path": str(p.resolve()), "sha256": digest(p)} for p in annotations],
        "groups": None
        if groups_file is None
        else {"path": str(groups_file.resolve()), "sha256": digest(groups_file)},
        "pool": {
            "embedded_clips": len(records),
            "labeled_clips": len(labeled),
            "unmatched_labels": unmatched,
            "special_labels": special,
            "roles": len(counts),
            "query_roles": sum(c >= 2 for c in counts.values()),
            "single_label_roles": sorted(n for n, c in counts.items() if c == 1),
        },
        "models": {m: {k: v for k, v in results[m].items() if k != "pairs"} for m in models},
        "examples": {
            "model": models[0],
            "rule": "For each character, the pair that is farthest apart. "
            "For different characters, the pair that is closest. "
            "And the queries where the nearest neighbor is the wrong person and leads by the "
            "most. Each clip appears at most once per kind.",
            **examples,
        },
    }
    write_json(out / "report.json", report)
    for m in models:
        write_json(out / f"pairs-{m}.json", results[m]["pairs"])
    return report
