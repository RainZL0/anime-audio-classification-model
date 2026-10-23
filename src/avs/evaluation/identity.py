"""Evaluate speaker identity only: exact time matching, wrong merges, missed merges, and how many
small groups each character is split into."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from avs.project import read_json, time_key


def pair_counts(truth: list[str], predicted: list[Any]) -> tuple[int, int, int]:
    """Count three totals of clip pairs: correctly linked same-person pairs, wrong merges, and
    missed merges.

    Computed from a table that counts each (human name, machine group number) combination, not by
    looping over every pair. During the threshold scan the same labels are counted thousands of
    times, and a pair-by-pair loop is too slow to use. The two methods give exactly the same result.
    """
    import numpy as np

    if len(truth) != len(predicted):
        raise ValueError("Human labels and predictions have different lengths")
    _, names = np.unique(np.asarray(truth, dtype=str), return_inverse=True)
    _, groups = np.unique(np.asarray(predicted, dtype=str), return_inverse=True)
    table = np.zeros((names.max(initial=-1) + 1, groups.max(initial=-1) + 1), dtype=np.int64)
    np.add.at(table, (names, groups), 1)

    def pairs(counts: Any) -> int:
        return int((counts * (counts - 1) // 2).sum())

    hits = pairs(table)
    return hits, pairs(table.sum(axis=0)) - hits, pairs(table.sum(axis=1)) - hits


def identity_metrics(truth: list[str], predicted: list[int]) -> dict[str, Any]:
    """Report wrong merges and missed merges together, so that putting every clip in its own group
    cannot pass as perfect recognition."""
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
    """Map a vocals file name to its episode name. The human archive only records the audio track
    file, so this mapping is how the episode is recovered from it."""
    if data.get("schema") != "avs.groups.v1":
        raise ValueError("Not a current grouping file")
    sources: dict[str, str] = {}
    for episode, info in data["episodes"].items():
        key = str(info["vocals"]).replace("\\", "/").rsplit("/", 1)[-1]
        if key in sources:
            raise ValueError(
                "Different episodes use vocals files with the same name, "
                "so old labels cannot be matched safely"
            )
        sources[key] = episode
    return sources


def annotated_clip_ids(data: dict[str, Any], annotations: list[Path]) -> set[str]:
    """Clips that already appear in the human archive, including special labels and blank ones. Used
    so that labeling is not scheduled twice."""
    sources = episode_by_source(data)
    by_time = {(r["episode"], time_key(r)): r["id"] for r in data["assignments"]}
    covered: set[str] = set()
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"{path} has an audio track that is not in this grouping")
        for clip in annotation["clips"]:
            clip_id = by_time.get((sources[source], time_key(clip)))
            if clip_id is not None:
                covered.add(clip_id)
    return covered


def match_annotations(
    data: dict[str, Any], annotations: list[Path]
) -> tuple[dict[str, str], int, int]:
    """Return only exactly matched human identities. Shared by evaluation and reference-sample
    splitting."""
    sources = episode_by_source(data)
    by_time = {(r["episode"], time_key(r)): r for r in data["assignments"]}
    matched: dict[str, str] = {}
    unmatched = special = 0
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"{path} has an audio track that is not in this grouping")
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
                raise ValueError("The same clip has conflicting human identity labels")
            matched[row["id"]] = name
    return matched, unmatched, special


def evaluate(
    groups_file: Path, annotations: list[Path], exclude_ids: set[str] | None = None
) -> dict[str, Any]:
    """Exact comparison against identities. Reference clips are excluded automatically, plus any
    extra ids excluded for a fair baseline comparison."""
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
        "note": "Only clips that are labeled and whose times match exactly are evaluated. "
        "Results tuned on the same batch are not an independent check.",
    }
