"""For each target character, train a small classifier on the human labels that answers "is this
them?". Then rank every clip that has a voiceprint.

Users only name the target characters. Everyone else is labeled "other" (see labels.py). So instead
of picking one character out of all characters, each target character gets its own logistic
regression (a standard, simple classifier). Clips the person confirmed for that character are
positive examples. Clips that are certainly not the target are negative examples.
"Other" only counts as a negative example for characters that were already targets when the label
was made. So adding or removing target characters midway does not misuse old labels.
The training set is only a few hundred to a few thousand clips, and one training run takes under a
second. So every label change retrains everything; there are no incremental updates.

**The classifier only picks among the characters it knows.** A voice that was never labeled may
still be guessed as some target character, and the confidence can still be fairly high. So there is
an extra similarity check: among the confirmed clips of the character the clip was assigned to,
the most similar one must be similar enough. The bar is not fixed. It is measured
from the current human labels: for each confirmed clip, take its highest similarity to the other
confirmed clips of the same character, and use a low-end value of those (the `FAMILIAR_QUANTILE`
percentile). Clips assigned to "other" skip this check, because a voice never seen is "other"
anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from avs.app.labels import OTHER

STRENGTH = 100.0
"""Regularization strength of the logistic regression. The value picked when episodes 1 and 2 were
held out in turn was between 30 and 1000. The middle value was used."""

AUTO_CONFIDENCE = 0.6
"""A confidence at or above this number counts as "confident". The interface then stops asking the
person to confirm each clip one by one.

Measured on episode 3, back when the model chose among all characters: clips with confidence of at
least 0.6 made up 80% of clips, and 97% of those were right. Below 0.6, only a little over 30% were
right. After switching to a separate judgment for each target character, only teo was measured.
Across episodes 1 to 3, each held out in turn, at 0.6 the model missed 13 of 230 teo clips, and no
other character was wrongly accepted as teo.
"""

FAMILIAR_QUANTILE = 0.05
"""The percentile of each character's nearest-clip similarity used as the "similar enough" bar.
95% of confirmed clips pass this bar."""

MIN_FAMILIAR_LABELS = 20
"""If there are fewer confirmed clips than this, no reliable bar can be measured. In that case the
machine never counts as confident."""


@dataclass(frozen=True)
class Guess:
    names: tuple[str, ...]
    """All target characters plus "other", sorted from most similar to least similar."""
    probabilities: tuple[float, ...]
    """For a target character, the chance that the clip is them. For "other", 1 minus the
    highest of those. The numbers do not necessarily add up to 1."""
    similarity: float
    """Cosine similarity (a score for how alike two voiceprints are) to the most similar confirmed
    clip of the most similar target character."""
    familiar: bool | None
    """When the top-ranked name is a target character: whether the similarity passed the bar. If it
    did not, this may be a person not seen before. When the top-ranked name is "other", this check
    is skipped and counted as passed. It is None when there are too few labels to measure a bar."""

    @property
    def confidence(self) -> float:
        return self.probabilities[0]

    def p(self, name: str) -> float:
        return self.probabilities[self.names.index(name)] if name in self.names else 0.0


@dataclass(frozen=True)
class Trained:
    guesses: dict[int, Guess]
    threshold: float | None


def familiar_threshold(features: Any, rows: list[int], names: list[str]) -> float | None:
    """For each confirmed clip, its highest similarity to the other confirmed clips of the same
    character. Then take a low-end percentile of those values."""
    import numpy as np

    if len(rows) < MIN_FAMILIAR_LABELS:
        return None
    labeled = features[rows]
    similarity = labeled @ labeled.T
    np.fill_diagonal(similarity, -np.inf)
    roles = np.array(names)
    best = []
    for i, name in enumerate(names):
        same = roles == name
        same[i] = False
        if same.any():
            best.append(float(similarity[i, same].max()))
    if len(best) < MIN_FAMILIAR_LABELS:
        return None
    return float(np.quantile(best, FAMILIAR_QUANTILE))


def train_and_predict(
    features: Any,
    examples: dict[str, tuple[list[int], list[int]]],
    rejects: dict[int, set[str]],
) -> Trained:
    """Give a prediction for each row of the voiceprint table.

    `examples` maps each target character to (positive row numbers, negative row numbers).
    `rejects` lists the rows and characters where the person said "not this character". On those
    rows, that character's probability is recorded as 0.
    """
    import numpy as np

    targets = list(examples)
    if not targets or len(features) == 0:
        return Trained({}, None)
    chances = np.zeros((len(features), len(targets)))
    nearest = np.full((len(features), len(targets)), -1.0)
    positive_rows: list[int] = []
    positive_names: list[str] = []
    for k, target in enumerate(targets):
        positives, negatives = examples[target]
        if not positives:
            continue
        positive_rows += positives
        positive_names += [target] * len(positives)
        if not negatives:
            # There are no negative examples yet, so it cannot tell who is not the target. Everyone
            # counts as similar.
            chances[:, k] = 1.0
        else:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(C=STRENGTH, max_iter=3000)
            model.fit(features[positives + negatives], [1] * len(positives) + [0] * len(negatives))
            chances[:, k] = model.predict_proba(features)[:, 1]
        # Similarity of each row to the most similar confirmed clip of this character. A confirmed
        # clip is not compared with itself.
        similarity = features @ features[positives].T
        similarity[positives, np.arange(len(positives))] = -np.inf
        nearest[:, k] = np.maximum(similarity.max(axis=1), -1.0)
    threshold = familiar_threshold(features, positive_rows, positive_names)

    guesses = {}
    for row in range(len(features)):
        own = chances[row].copy()
        for name in rejects.get(row, ()):
            if name in targets:
                own[targets.index(name)] = 0.0
        best = int(np.argmax(own))
        scored = [(targets[k], float(own[k])) for k in range(len(targets))]
        scored.append((OTHER, 1.0 - float(own[best])))
        scored.sort(key=lambda pair: -pair[1])
        close = float(nearest[row, best])
        familiar = None if threshold is None else (scored[0][0] == OTHER or close >= threshold)
        guesses[row] = Guess(
            names=tuple(name for name, _ in scored),
            probabilities=tuple(round(p, 4) for _, p in scored),
            similarity=round(close, 4),
            familiar=familiar,
        )
    return Trained(guesses, threshold)
