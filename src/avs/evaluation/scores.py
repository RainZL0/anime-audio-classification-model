"""Check whether normalized similarity scores are worth plugging into grouping: first look only at
whether the pair scores of the same character and of different characters can be told apart.

Grouping rules only decide which scores count as "linked". They cannot change the scores
themselves. So first measure two things on the pairs from human labels. If the two groups cannot
be separated, there is no point in plugging the scores into clustering:

- **Ranking accuracy** (`auc`): take a random pair of clips from the same character and a random
  pair from different characters, and count how often the same-character pair gets the higher
  score. Pure chance gives 0.50.
- **Equal error rate** (`eer`): move the threshold to the spot where "same character wrongly split
  apart" and "different characters wrongly merged" happen equally often. The error rate at that
  spot is the number reported.

Results are split by clip duration and by whether the pair crosses episodes, because some tricks
only help in one range. An overall figure that looks flat can still hide an improvement on short
clips.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from avs.project import write_json

DURATION_BINS = ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 3.0), (3.0, 6.0))
"""The short end is split finely, because all the known weak spots are concentrated there, and
whether to include clips under 1 second depends directly on how much the difference is around 1
second. The long end does not differ much anyway, so it does not need a fine split."""


def duration_bin(seconds: float) -> str:
    for low, high in DURATION_BINS:
        if low <= seconds < high:
            return f"{low:g}-{high:g}s"
    return f">={DURATION_BINS[-1][1]:g}s"


def separation(same: Any, other: Any) -> dict[str, Any]:
    """Whether the scores of same-character and different-character pairs can be told apart. A
    higher score means more alike."""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    if not len(same) or not len(other):
        return {"same_pairs": len(same), "other_pairs": len(other), "auc": None, "eer": None}
    labels = np.concatenate([np.ones(len(same)), np.zeros(len(other))])
    scores = np.concatenate([same, other])
    auc = float(roc_auc_score(labels, scores))
    # Equal error rate: scan all candidate thresholds and take the point where the two error rates
    # are closest.
    grid = np.quantile(scores, np.linspace(0, 1, 401))
    miss = np.array([float((same < cut).mean()) for cut in grid])
    false = np.array([float((other >= cut).mean()) for cut in grid])
    at = int(np.argmin(np.abs(miss - false)))
    return {
        "same_pairs": len(same),
        "other_pairs": len(other),
        "auc": round(auc, 4),
        "eer": round(float((miss[at] + false[at]) / 2), 4),
        "same_median": round(float(np.median(same)), 4),
        "other_median": round(float(np.median(other)), 4),
    }


def compare_norms(
    episodes: list[Path],
    annotations: list[Path],
    models: list[str],
    out: Path,
    methods: list[str] | None = None,
    window: float = 0.0,
) -> dict[str, Any]:
    """On the pairs from human labels, compare the separation of raw cosine similarity against each
    normalization."""
    import numpy as np

    from avs.evaluation.diagnose import load_pool
    from avs.evaluation.identity import match_annotations
    from avs.stages.normalize import NORMS, normalized_similarity

    if out.exists():
        raise ValueError(
            f"Report already exists. Use another file name to keep the previous result: {out}"
        )
    chosen = list(methods or NORMS)
    if any(m not in NORMS for m in chosen) or len(set(chosen)) != len(chosen):
        raise ValueError(f"Normalization must be one of {', '.join(NORMS)}, and must not repeat")

    info, records, vectors = load_pool(episodes, models, window)
    matched, unmatched, special = match_annotations(
        {"schema": "avs.groups.v1", "episodes": info, "assignments": records}, annotations
    )
    index = {row["id"]: i for i, row in enumerate(records)}
    labeled = [(index[i], name) for i, name in matched.items() if i in index]
    if len(labeled) < 3:
        raise ValueError("Too few human labels can be matched exactly to compare separation")

    pairs = list(itertools.combinations(sorted(labeled), 2))
    same = np.array([a[1] == b[1] for a, b in pairs])
    both_short = np.array(
        [duration_bin(min(_seconds(records[a[0]]), _seconds(records[b[0]]))) for a, b in pairs]
    )
    cross = np.array([records[a[0]]["episode"] != records[b[0]]["episode"] for a, b in pairs])
    rows = np.array([a[0] for a, _ in pairs])
    cols = np.array([b[0] for _, b in pairs])

    results = []
    for model in models:
        for method in chosen:
            scores = normalized_similarity(vectors[model], method)[rows, cols]
            entry: dict[str, Any] = {
                "model": model,
                "norm": method,
                "overall": separation(scores[same], scores[~same]),
                "by_min_duration": {
                    label: separation(
                        scores[same & (both_short == label)], scores[~same & (both_short == label)]
                    )
                    for label in sorted(set(both_short))
                },
                "cross_episode": separation(scores[same & cross], scores[~same & cross]),
                "same_episode": separation(scores[same & ~cross], scores[~same & ~cross]),
            }
            results.append(entry)

    report = {
        "schema": "avs.score_norm.v1",
        "window_seconds": window,
        "labeled_clips": len(labeled),
        "unmatched_labels": unmatched,
        "special_labels": special,
        "pairs": len(pairs),
        "results": results,
        "note": "Only compares how well the scores separate the groups; no grouping is done. "
        "No separate batch of unrelated clips is available to use as the reference set, "
        "so the reference clips are all clips in this batch. "
        "That means the k most similar clips that asnorm picks will include clips of the same "
        "character, so same-character scores are effectively used as the baseline, "
        "which weakens its effect.",
    }
    write_json(out, report)
    return report


def _seconds(row: dict[str, Any]) -> float:
    return float(row["end"]) - float(row["start"])
