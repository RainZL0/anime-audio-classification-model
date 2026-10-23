"""Test whether a few human identities can link fragmented groups together; reference labels are
kept strictly apart from scoring labels."""

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
    """Merge only original groups that contain the same-named references. Original groups with no
    reference, or with conflicting references, stay separate."""
    if data.get("schema") != "avs.groups.v1" or data.get("support"):
        raise ValueError("Needs an original grouping that has not used identity references yet")
    by_id = {r["id"]: r for r in data["assignments"]}
    names: dict[str, set[str]] = defaultdict(set)
    for clip_id, name in support.items():
        if clip_id not in by_id or not by_id[clip_id]["speaker"]:
            raise ValueError("Reference clips must exist and already have a voiceprint group")
        if not name or name.startswith("__"):
            raise ValueError("A reference must be a clear human character name")
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
        "rule": "Only groups that contain a same-named human reference are linked. "
        "A whole group being one identity is still an unverified assumption.",
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
    """A clip is assigned to the nearest reference's character only if that reference is close
    enough and is ahead of every other character by the margin. Otherwise the clip keeps its
    original group. References are not expanded recursively."""
    import numpy as np

    if not 0 < threshold <= 2 or not 0 <= margin <= 2:
        raise ValueError("Distance and margin must be within the cosine distance range")
    # Shared reference validity check. This method assigns from the original clips again, and does
    # not use the merged-group results.
    link_reference_groups(data, support)
    indices = {r["id"]: i for i, r in enumerate(records)}
    if not support or any(key not in indices for key in support):
        raise ValueError("Every reference must have a voiceprint")
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
        "rule": "Distances are computed only against the original human references. "
        "Predicted clips are not used as new references. "
        "Clips that fail the test keep their original group.",
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
    """Use 1 or 2 references per person, each with seeds 0 to 19. References are not picked, and
    candidates are not saved, based on evaluation scores."""
    if out.exists():
        raise ValueError(f"Output directory already exists: {out}")
    data = read_json(groups_file)
    records: list[dict[str, Any]] = []
    vectors = None
    if nearest:
        import numpy as np

        matrices = []
        for info in data["episodes"].values():
            directory = Path(info["directory"])
            if digest(directory / "segments.json") != info["segments_sha256"]:
                raise ValueError("The original grouping does not match the current clips")
            own_records, own_vectors = load_embeddings(directory, data["model"])
            records.extend(own_records)
            matrices.append(own_vectors)
        vectors = np.concatenate(matrices)
        by_id = {r["id"]: r for r in data["assignments"]}
        if any(any(by_id[r["id"]][k] != v for k, v in r.items()) for r in records):
            raise ValueError("Voiceprint clips do not match the original grouping")
    matched, unmatched, special = match_annotations(data, annotations)
    assigned = {r["id"] for r in data["assignments"] if r["speaker"] is not None}
    by_role: dict[str, list[str]] = defaultdict(list)
    for clip_id, name in matched.items():
        if clip_id in assigned:
            by_role[name].append(clip_id)
    if not roles or len(set(roles)) != len(roles):
        raise ValueError("Need unique reference role names")
    if any(len(by_role[name]) < 4 for name in roles):
        raise ValueError(
            "Each reference role needs at least 4 labels, to leave at least 2 clips for scoring"
        )
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
                        raise ValueError(
                            "Reference method and baseline have different scored clip counts"
                        )
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
        "candidate_selection": "Fixed at 2 references per person, seed 0. "
        "The nearest-reference method uses 0.5. Not picked by score.",
        "note": "Reference-merge experiment on the same batch of old labels. "
        "All references are excluded from scoring. Repeated splits are correlated, "
        "so this is not an independent test on new episodes.",
    }
    write_json(out / "report.json", report)
    write_json(out / "candidate.json", candidate)
    write_json(out / "candidate-evaluation.json", evaluate(out / "candidate.json", annotations))
    return report
