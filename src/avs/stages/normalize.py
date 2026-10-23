"""Score normalization: instead of comparing the similarity of two clips directly, first look at how
high a score each clip usually gets, then compare how far this pair rises above that.

**Why this was tried.** Measurements showed that the distance between two clips of the same
character grows systematically as the clips get shorter (median distance: under 1.5 s 0.496, 1.5-3 s
0.416, 3-6 s 0.322). It looked as if a short clip did not resemble anyone much, not just that it did
not resemble its own character. If that were true, one threshold could not suit both long and short
clips: set it where long clips fit, and all the short clips would fail to link. What this does is
measure how similar each clip is to a pile of unrelated clips, subtract that baseline level, and
then ask how far this pair rises above its own baseline.

**Two methods.** `snorm` takes the mean and spread over all the unrelated clips. `asnorm` uses only
the `k` most similar ones, because pairs that are very far apart carry little information about who
is a close neighbour. The baseline clips are all the clips in this batch, except the clip itself. We
have no separate batch of clips unrelated to this one, so the `k` most similar clips chosen by
`asnorm` inevitably include clips of the same character. That means same-character scores are used
as the baseline, which weakens the effect.

**The result: it did not help.** See EXPERIMENTS. The code is kept because it is the evidence for
that result.

The return value is the normalized similarity (larger means more alike), not a distance. The caller
decides whether to convert it to a distance. The normalized values are standard scores (how many
spreads a value sits above the average), on a different scale from cosine distance, so the original
threshold cannot be applied to them.
"""

from __future__ import annotations

from typing import Any

NORMS = ("none", "snorm", "asnorm")
ASNORM_K = 100
"""How many of the most similar clips asnorm uses as its baseline. About one fifth of the 485 clips
in this batch."""


def normalized_similarity(vectors: Any, method: str = "none", k: int = ASNORM_K) -> Any:
    """Pairwise similarity, normalized by `method`. `vectors` must be unit vectors."""
    import numpy as np

    if method not in NORMS:
        raise ValueError(f"Normalization must be one of {', '.join(NORMS)}, got {method}")
    similarity = np.asarray(vectors, dtype=np.float64) @ np.asarray(vectors, dtype=np.float64).T
    if method == "none" or len(similarity) < 3:
        return similarity

    count = len(similarity)
    cohort = similarity.copy()
    np.fill_diagonal(cohort, -np.inf)
    if method == "snorm":
        # A clip cannot use itself as its own baseline, so remove the diagonal before computing the
        # statistics.
        keep = ~np.eye(count, dtype=bool)
        rows = similarity[keep].reshape(count, count - 1)
    else:
        take = max(2, min(k, count - 1))
        rows = np.sort(cohort, axis=1)[:, -take:]
    mean = rows.mean(axis=1)
    spread = rows.std(axis=1)
    spread[spread < 1e-9] = 1e-9
    left = (similarity - mean[:, None]) / spread[:, None]
    right = (similarity - mean[None, :]) / spread[None, :]
    return 0.5 * (left + right)
