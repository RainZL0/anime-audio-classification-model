"""How many labels before the machine's guesses can be trusted? Replays a workspace's confirmed
labels for one target character as a person would make them in Scenes (line by line, in time
order), retrains after each step the way the interface does, and scores the guesses on episodes
that are never trained on. Also replays the same labels in random order.

    uv run python scripts/replay_labels.py workspace teo --train ep01,ep02 --test ep03

Only lines labeled the target or "Other" by a person count; "low quality" lines are left out.
The results for Tokai Teio are in docs/HOW_IT_WORKS.md#how-many-labels-before-the-guesses-are-good.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

import numpy as np

from avoc.app.labels import OTHER, LabelStore
from avoc.app.model import AUTO_CONFIDENCE, train_and_predict
from avoc.app.workspace import DEFAULT_MODELS, GROUPING_MODEL, Clip, load_workspace

STEPS = [2, 4, 6, 8, 10, 15, 20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 400, 500]
RUNS = 10
"""Random orders replayed; the median of each number is shown."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workspace", type=Path)
    parser.add_argument("target", help="the target character's name")
    parser.add_argument("--train", required=True, help="episodes to replay, comma-separated")
    parser.add_argument("--test", required=True, help="episodes to score on, comma-separated")
    args = parser.parse_args()

    ws = load_workspace(args.workspace, DEFAULT_MODELS, GROUPING_MODEL)
    store = LabelStore(ws.labels_dir)

    def truth(clip: Clip) -> bool | None:
        """True for the target, False for "Other", None for lines without a usable label."""
        name = store.labels.get(clip.id)
        if clip.row is None or name not in (args.target, OTHER) or clip.id in store.unusable:
            return None
        return name == args.target

    def labeled(episodes: str) -> list[Clip]:
        wanted = set(episodes.split(","))
        clips = [c for c in ws.clips if c.episode in wanted and truth(c) is not None]
        return sorted(clips, key=lambda c: (c.episode, c.start))

    replay, test = labeled(args.train), labeled(args.test)
    rows = [c.row for c in test if c.row is not None]
    is_target = np.array([truth(c) for c in test])
    steps = [n for n in STEPS if n < len(replay)] + [len(replay)]

    def measure(order: list[Clip], n: int) -> dict[str, Any]:
        done = order[:n]
        pos = [c.row for c in done if c.row is not None and truth(c)]
        neg = [c.row for c in done if c.row is not None and not truth(c)]
        trained = train_and_predict(ws.features, {args.target: (pos, neg)}, {}, min_labels=1)
        found: dict[str, Any] = {"n": n, "target": len(pos), "guessing": bool(trained.guesses)}
        if not trained.guesses:
            return found
        p = np.array([trained.guesses[r].p(args.target) for r in rows])
        right = (p >= 0.5) == is_target
        sure = np.maximum(p, 1 - p) >= AUTO_CONFIDENCE
        # How far the chances are from what happens: in each tenth of the 0-1 range, the average
        # chance against the share that really is the target, weighted by the lines there.
        bins = np.minimum((p * 10).astype(int), 9)
        gap = sum(
            abs(p[bins == b].mean() - is_target[bins == b].mean()) * (bins == b).sum()
            for b in range(10)
            if (bins == b).any()
        ) / len(p)
        return found | {
            "right": right.mean(),
            "right_when_sure": right[sure].mean() if sure.any() else float("nan"),
            "found_sure": (right & is_target & sure).sum() / is_target.sum(),
            "gap": gap,
        }

    def line(r: dict[str, Any]) -> str:
        head = f"{r['n']:4.0f} {r['target']:6.0f} |"
        if not r["guessing"]:
            return f"{head} no guess yet"
        return (
            f"{head} {r['right']:6.0%} {r['right_when_sure']:9.0%}"
            f" {r['found_sure']:9.0%} {r['gap']:9.3f}"
        )

    print(
        f"Replayed: {len(replay)} lines of {args.train}. Scored on {len(test)} lines of "
        f"{args.test}, {int(is_target.sum())} of them {args.target} "
        f"(guessing everyone is Other is right {1 - is_target.mean():.0%})."
    )
    header = "   n target |  right  if sure  found sure  chance gap"
    print("\nIn time order, as in Scenes:\n" + header)
    for n in steps:
        print(line(measure(replay, n)))

    print(f"\nIn random order, median of {RUNS} runs:\n" + header)
    runs = []
    for seed in range(RUNS):
        order = replay[:]
        random.Random(seed).shuffle(order)
        runs.append([measure(order, n) for n in steps])
    for i, n in enumerate(steps):
        got = [run[i] for run in runs if run[i]["guessing"]]
        if not got:
            print(f"{n:4d}      - | no guess yet")
            continue
        median = {k: float(np.median([g[k] for g in got])) for k in got[0] if k != "guessing"}
        print(line(median | {"guessing": True}) + f"  ({len(got)}/{RUNS} guessing)")


if __name__ == "__main__":
    main()
