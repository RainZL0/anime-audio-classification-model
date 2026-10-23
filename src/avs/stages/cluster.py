"""Global clip grouping. Clips are not first squeezed into one unsplittable center point per
episode.

The linking rule only changes which distances count as "linked". It does not change the voiceprints
or the distances themselves.
average / single / complete are the three linkages of hierarchical clustering. mutual_knn links two
clips only when each one is among the other's k nearest neighbours
and their distance is within the threshold, then takes the connected groups. two_stage first groups
only the clips at least SHORT_SECONDS long, using average linkage,
then attaches each short clip to the nearest group whose nearest member is within the threshold and
whose lead over the second group is at least ATTACH_MARGIN.
Short clips that cannot be attached get one more round of average linkage among themselves, so
characters that only have short clips can still form groups.
The diagnostics showed that all the missed merges involve short clips, so they are handled
separately.
"""

from __future__ import annotations

from typing import Any

METHODS = ("average", "single", "complete", "mutual_knn", "two_stage")
MUTUAL_K = 3
"""Number of nearest neighbours each clip considers under the mutual nearest-neighbour rule. It is a
fixed constant, so it cannot be tuned together with the threshold to overfit the groups."""
SHORT_SECONDS = 1.5
"""Upper duration limit for a clip to count as short in two_stage. Taken from the duration breakdown
of the missed-merge pairs in the diagnostics."""
ATTACH_MARGIN = 0.05
"""Cosine distance by which the nearest group must lead the second-nearest group before a short clip
is attached to it. Matches the lead used in the reference experiment."""

POOL_QUANTILE = 0.01
"""Quantile used to set the threshold from the pool: all pairwise distances in the pool are sorted
from near to far, and the one at the 1% mark is taken.

This low a quantile is used because it follows the share of pairs from the same character among all
pairs. The more characters there are in the pool, the sparser the very close pairs become, and this
distance grows, which moves the threshold in the direction it needs to go.
High quantiles such as the median are almost all pairs from different characters. They do not change
as the pool grows, so they are of no use here."""

POOL_MULTIPLIERS = {"anime-va": 1.275}
"""Multiplier used to set the threshold from the pool, one per model. The product is the threshold.

1.275 was set like this: on the pool of 1176 clips from the three episodes so far, it gives the 0.70
that anime-va currently uses.
**So today this rule groups exactly like a fixed 0.70. It only starts to diverge as the corpus keeps
growing.** When it diverges, the threshold moves outward as the pool grows, which offsets the fact
that bigger pools merge more conservatively.

The multiplier sets how loose or tight the grouping is. That is a separate question from whether the
result is stable. A multiplier of 1.38 (which gives 0.70 when only episode 3 is in the pool) is just
as stable, but it is a much looser setting: links in episode 3 rise from 2095 to 3075, and wrong
merges in episode 1 rise from 11 to 155.
Wrong merges are the more costly kind of error in this project, so the conservative value was
chosen.

**This multiplier was picked on the labels from the three episodes so far, and it has not been
independently tested.** See EXPERIMENTS.md."""

MAX_QUANTILE_PAIRS = 20_000_000
"""Maximum number of distance pairs used to compute a quantile. Beyond this, that many pairs are
sampled at random, so the full distance table does not run out of memory.
13 episodes give about 5000 clips and 12.5 million pairs, which is still within this limit."""


def pool_threshold(vectors: Any, multiplier: float, quantile: float = POOL_QUANTILE) -> float:
    """Set the threshold from the pool's own distances, instead of hard-coding one number.

    A fixed threshold drifts out of place as the clip pool grows: with the same number, the bigger
    the pool, the more conservative the merging (see HISTORY.md).
    Here the distances inside this pool are looked at first, and then the threshold is set with the
    same ratio.
    """
    import numpy as np

    if not 0 < quantile < 1:
        raise ValueError("The quantile must be between 0 and 1")
    if not multiplier > 0:
        raise ValueError("The multiplier must be greater than 0")
    if len(vectors) < 2:
        raise ValueError("At least two clips are needed to measure the distances inside the pool")
    total = len(vectors) * (len(vectors) - 1) // 2
    if total <= MAX_QUANTILE_PAIRS:
        from scipy.spatial.distance import pdist

        distances = pdist(vectors, metric="cosine")
    else:
        rng = np.random.default_rng(0)
        rows = rng.integers(0, len(vectors), MAX_QUANTILE_PAIRS)
        cols = rng.integers(0, len(vectors) - 1, MAX_QUANTILE_PAIRS)
        cols += cols >= rows  # Do not pair a clip with itself. That distance is always 0.
        distances = 1 - np.einsum("ij,ij->i", vectors[rows], vectors[cols])
    return float(np.quantile(distances, quantile) * multiplier)


def cluster(
    vectors: Any, threshold: float = 0.5, method: str = "average", durations: Any = None
) -> Any:
    """Compare the voiceprints of all clips directly. 0.5 is a starting point that still needs
    independent verification. Returns the group number of each clip."""
    import numpy as np

    if method not in METHODS:
        raise ValueError(f"Linking rule must be one of {', '.join(METHODS)}, got {method}")
    if method == "two_stage":
        if durations is None or len(durations) != len(vectors):
            raise ValueError("two_stage needs the duration of each clip")
        return _two_stage(vectors, np.asarray(durations, dtype=float), threshold)
    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    if method == "mutual_knn":
        return _mutual_knn(vectors, threshold)
    from sklearn.cluster import AgglomerativeClustering

    return AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="cosine", linkage=method
    ).fit_predict(vectors)


def _mutual_knn(vectors: Any, threshold: float) -> Any:
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    distances = 1 - vectors @ vectors.T
    np.fill_diagonal(distances, np.inf)
    k = min(MUTUAL_K, len(vectors) - 1)
    nearest = np.argsort(distances, axis=1, kind="stable")[:, :k]
    rows = np.repeat(np.arange(len(vectors)), k)
    cols = nearest.ravel()
    forward = coo_matrix((np.ones(len(rows), dtype=bool), (rows, cols)), shape=distances.shape)
    mutual = forward.multiply(forward.T).tocoo()
    keep = distances[mutual.row, mutual.col] <= threshold
    graph = coo_matrix(
        (np.ones(int(keep.sum()), dtype=bool), (mutual.row[keep], mutual.col[keep])),
        shape=distances.shape,
    )
    return connected_components(graph, directed=False)[1]


def _two_stage(vectors: Any, durations: Any, threshold: float) -> Any:
    import numpy as np

    long_index = np.where(durations >= SHORT_SECONDS)[0]
    short_index = np.where(durations < SHORT_SECONDS)[0]
    labels = np.full(len(vectors), -1, dtype=int)
    if len(long_index):
        labels[long_index] = cluster(vectors[long_index], threshold, "average")
    if len(long_index) and len(short_index):
        long_labels = labels[long_index]
        groups = np.unique(long_labels)
        distances = 1 - vectors[short_index] @ vectors[long_index].T
        # For each short clip, the distance to the nearest member of each long-clip group. Attach it
        # only to the group that is clearly nearest.
        nearest = np.stack([distances[:, long_labels == g].min(axis=1) for g in groups], axis=1)
        order = np.argsort(nearest, axis=1, kind="stable")
        for row, clip in enumerate(short_index):
            best = nearest[row, order[row, 0]]
            second = nearest[row, order[row, 1]] if len(groups) > 1 else np.inf
            if best <= threshold and second - best >= ATTACH_MARGIN:
                labels[clip] = groups[order[row, 0]]
    leftover = np.where(labels < 0)[0]
    if len(leftover):
        offset = int(labels.max()) + 1
        labels[leftover] = offset + cluster(vectors[leftover], threshold, "average")
    return labels
