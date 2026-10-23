"""Leave-one-episode-out check: train on the human labels of the other episodes, then assign each
clip of the held-out episode directly to a character name.

Three methods are compared side by side. All of them use only cached voiceprints, nothing is
recomputed:

- **Most similar one**: a clip gets the name of the most similar already-labeled clip in the
  training set. Grouping works on this same one-by-one comparison.
- **Character average**: the labeled clips of each character are averaged into one direction, and
  each clip goes to the nearest character.
- **Small classifier**: logistic regression (a standard method that gives each character a
  probability) trained on the training set's voiceprints. Its regularization strength is chosen
  only by cross-validation inside the training set, meaning training on some episodes and testing
  on the one left out. The held-out episode is not looked at.

Each prediction comes with a confidence score. Clips are sorted from high confidence to low, and
the accuracy is reported for the top 50%, the top 80%, and all clips. A character that appears in
the held-out episode but not in the training set is always counted as wrong, and kept in the
denominator. The number of such clips is reported separately.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

from avs.pipeline import load_embeddings
from avs.project import load_episode, read_json, time_key, write_json

DURATION_BINS = ((0.5, 1.0), (1.0, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, math.inf))
COVERAGES = (0.5, 0.8, 1.0)
STRENGTHS = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
"""Candidate values for the logistic regression regularization strength. A larger number means a
looser constraint on the model. Only chosen inside the training set."""

METHODS = ("nearest", "centroid", "logistic")


def labels_by_episode(
    directories: list[Path], annotations: list[Path]
) -> dict[str, dict[str, str]]:
    """Human identities for each episode: episode name to a map of clip ID to character name. Only
    labels whose time matches exactly to the millisecond are collected. Special labels are not
    collected."""
    episodes = {}
    for directory in directories:
        episode, rows = load_episode(directory)
        source = str(Path(episode["vocals"])).replace("\\", "/").rsplit("/", 1)[-1]
        episodes[source] = (episode["name"], {time_key(r): r["id"] for r in rows})
    found: dict[str, dict[str, str]] = {name: {} for name, _ in episodes.values()}
    for path in annotations:
        annotation = read_json(path)
        source = str(annotation["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in episodes:
            raise ValueError(f"{path} has an audio track that is not in these episode folders")
        name, by_time = episodes[source]
        for clip in annotation["clips"]:
            person = clip.get("name")
            if not person or person.startswith("__"):
                continue
            clip_id = by_time.get(time_key(clip))
            if clip_id is None:
                continue
            if found[name].get(clip_id, person) != person:
                raise ValueError("The same clip has conflicting human identity labels")
            found[name][clip_id] = person
    return found


def features(directory: Path, models: list[str]) -> tuple[list[dict[str, Any]], Any]:
    """Voiceprints for one episode. With several models, each one is unit length. They are aligned
    by clip ID, joined side by side, and then normalized as a whole."""
    import numpy as np

    base: list[dict[str, Any]] = []
    parts = []
    for model in models:
        records, vectors = load_embeddings(directory, model)
        order = {r["id"]: i for i, r in enumerate(records)}
        if not base:
            base = records
        elif set(order) != {r["id"] for r in base}:
            raise ValueError("Models cover different clips, so they cannot be joined together")
        parts.append(vectors[[order[r["id"]] for r in base]])
    joined = np.concatenate(parts, axis=1)
    return base, joined / np.linalg.norm(joined, axis=1, keepdims=True)


def _class_scores(method: str, train: Any, names: list[str], test: Any, strength: float) -> Any:
    """Return (list of character names, each test clip's score for each character). A higher score
    means more alike."""
    import numpy as np

    roles = sorted(set(names))
    index = np.array([roles.index(n) for n in names])
    if method == "nearest":
        similarity = test @ train.T
        scores = np.full((len(test), len(roles)), -np.inf)
        for k in range(len(roles)):
            scores[:, k] = similarity[:, index == k].max(axis=1)
        return roles, scores
    if method == "centroid":
        centers = np.stack([train[index == k].mean(axis=0) for k in range(len(roles))])
        centers /= np.linalg.norm(centers, axis=1, keepdims=True)
        return roles, test @ centers.T
    if method == "logistic":
        from sklearn.linear_model import LogisticRegression

        if len(roles) == 1:
            return roles, np.ones((len(test), 1))
        model = LogisticRegression(C=strength, max_iter=5000)
        model.fit(train, index)
        return [roles[k] for k in model.classes_], model.predict_proba(test)
    raise ValueError(f"Unknown method {method!r}")


def predict(
    method: str, train: Any, names: list[str], test: Any, strength: float = 10.0
) -> tuple[list[str], list[float]]:
    """Predicted character and confidence for each test clip.

    For logistic regression, the confidence is the probability the model gives. For the other two
    methods, it is how much the first place beats the second place. If there is only one character,
    it is recorded as 1.
    """
    import numpy as np

    roles, scores = _class_scores(method, train, names, test, strength)
    order = np.argsort(-scores, axis=1)
    top = scores[np.arange(len(test)), order[:, 0]]
    if method == "logistic":
        confidence = top
    elif len(roles) > 1:
        confidence = top - scores[np.arange(len(test)), order[:, 1]]
    else:
        confidence = np.ones(len(test))
    return [roles[k] for k in order[:, 0]], [float(c) for c in confidence]


def pick_strength(pool: dict[str, tuple[Any, list[str]]]) -> tuple[float, dict[str, float]]:
    """Choose the logistic regression regularization strength, holding out one training episode at a
    time. When there is only one training episode, use the middle value."""
    import numpy as np

    if len(pool) < 2:
        return 10.0, {}
    results: dict[str, float] = {}
    for strength in STRENGTHS:
        right = total = 0
        for held in pool:
            train = np.concatenate([v for e, (v, _) in pool.items() if e != held])
            names = [n for e, (_, ns) in pool.items() if e != held for n in ns]
            guesses, _ = predict("logistic", train, names, pool[held][0], strength)
            right += sum(g == t for g, t in zip(guesses, pool[held][1], strict=True))
            total += len(guesses)
        results[f"{strength:g}"] = round(right / total, 4)
    best = max(STRENGTHS, key=lambda s: (results[f"{s:g}"], -s))
    return best, results


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def summarize(
    truth: list[str], guesses: list[str], confidence: list[float], durations: list[float]
) -> dict[str, Any]:
    """Accuracy: overall, by clip duration bins, and for the top few proportions ranked by
    confidence from high to low."""
    right = [g == t for g, t in zip(guesses, truth, strict=True)]
    by_duration = {}
    for low, high in DURATION_BINS:
        inside = [r for r, d in zip(right, durations, strict=True) if low <= d < high]
        label = f"{low:g}-{high:g}s" if math.isfinite(high) else f">={low:g}s"
        by_duration[label] = {"clips": len(inside), "accuracy": _rate(inside)}
    ranked = [r for _, r in sorted(zip(confidence, right, strict=True), key=lambda p: -p[0])]
    by_coverage = {
        f"top{round(share * 100)}%": _rate(ranked[: max(1, math.ceil(share * len(ranked)))])
        for share in COVERAGES
    }
    return {"accuracy": _rate(right), "by_duration": by_duration, "by_confidence": by_coverage}


def classify_check(
    directories: list[Path],
    test: str,
    annotations: list[Path],
    out: Path,
    models: list[str],
) -> dict[str, Any]:
    """Train on the human labels of every episode except `test`, and score only on the `test`
    episode."""
    import numpy as np

    if out.exists():
        raise ValueError(f"{out} already exists, use another file name")
    labels = labels_by_episode(directories, annotations)
    if not labels.get(test):
        raise ValueError(f"No labels for {test} in these human archives, so it cannot be scored")

    pool: dict[str, tuple[Any, list[str]]] = {}
    held: tuple[list[dict[str, Any]], Any, list[str]] | None = None
    for directory in directories:
        episode, _ = load_episode(directory)
        records, vectors = features(directory, models)
        own = labels[episode["name"]]
        keep = [i for i, r in enumerate(records) if r["id"] in own]
        names = [own[records[i]["id"]] for i in keep]
        if episode["name"] == test:
            held = ([records[i] for i in keep], vectors[keep], names)
        elif keep:
            pool[episode["name"]] = (vectors[keep], names)
    if held is None or not pool:
        raise ValueError(
            "Need the tested episode, plus at least one training episode that has labels"
        )

    records, test_vectors, truth = held
    train = np.concatenate([v for v, _ in pool.values()])
    train_names = [n for _, ns in pool.values() for n in ns]
    durations = [float(r["end"] - r["start"]) for r in records]
    seen = set(train_names)
    strength, search = pick_strength(pool)

    results = {}
    per_clip: dict[str, list[dict[str, Any]]] = {}
    for method in METHODS:
        guesses, confidence = predict(method, train, train_names, test_vectors, strength)
        results[method] = summarize(truth, guesses, confidence, durations)
        per_clip[method] = [
            {
                "id": r["id"],
                "start": r["start"],
                "end": r["end"],
                "truth": t,
                "predicted": g,
                "confidence": round(c, 4),
            }
            for r, t, g, c in zip(records, truth, guesses, confidence, strict=True)
        ]

    report = {
        "schema": "avs.classify-check.v1",
        "models": models,
        "train_episodes": {e: len(ns) for e, (_, ns) in pool.items()},
        "test_episode": test,
        "test_clips": len(truth),
        "train_roles": len(seen),
        "test_roles": len(set(truth)),
        "unseen_role_clips": sum(t not in seen for t in truth),
        "unseen_roles": dict(Counter(t for t in truth if t not in seen)),
        "logistic_strength": strength,
        "logistic_strength_search": search,
        "results": results,
        "clips": per_clip,
        "note": "Clips shorter than 0.5 seconds have no voiceprint, so they are not included. "
        "Characters that are not in the training set are still counted as wrong.",
    }
    write_json(out, report)
    return report
