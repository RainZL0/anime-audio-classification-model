"""Compare cached voiceprints on the same clips and human labels, keeping the full threshold
curve."""

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
    """Refuse to overwrite a result, or to compare voiceprints built from different clip sets. All
    scores are exploratory, not an independent acceptance test."""
    methods = methods or ["average"]
    if out.exists():
        raise ValueError(f"Report already exists: {out}")
    if not models or len(set(models)) != len(models) or not thresholds:
        raise ValueError("Need unique model names and at least one threshold")
    if len(set(methods)) != len(methods):
        raise ValueError("Linking methods must not be repeated")
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
            raise ValueError("Models cover different clips, so they cannot be compared directly")
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
    # A row is dominated only when another row has no more wrong merges, at least as many
    # correct same-person links, and is strictly better on one of the two. Fewer groups alone
    # does not mean the identities are more accurate, so it is not used as a reason.
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
        "note": "Exploration curve on the same batch of human labels. The thresholds were chosen "
        "using these labels, so this cannot serve as an independent check.",
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
