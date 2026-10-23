"""在人工标签上给每个目标角色训练一个「是不是 TA」的小分类器，给每条有声纹的片段排出名次。

用户只给目标角色起名字，其余的人标「其他」（见 labels.py）。所以不在全部角色里挑一个，而是
每个目标角色单独训练一个逻辑回归：这个角色确认过的片段是正例，确定不是 TA 的片段是反例。
「其他」只对标它的那一刻已经是目标的角色算反例，所以中途加减目标角色不会把旧标签用错。
训练集只有几百到几千条，一次训练不到一秒，所以每改一条标签都整个重训，不做增量更新。

**分类器只会在认识的角色里挑。** 一个从没标过的声音，也可能被说成某个目标角色，而且把握
还不低。所以另加一道「像不像」的检查：这句和它被归给的角色里最像的那一条已确认片段，
相似度要够高。够高的标准不写死，从当前的人工标签里量：每条已确认片段和同角色其余片段
最像的那个相似度，取其中偏低的一端（第 `FAMILIAR_QUANTILE` 分位）。归给「其他」的不做这道
检查：没见过的声音本来就是「其他」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from avs.app.labels import OTHER

STRENGTH = 100.0
"""逻辑回归的正则强度。第 1、2 集互相留出时挑出来的值在 30 到 1000 之间，取中间。"""

AUTO_CONFIDENCE = 0.6
"""把握到这个数就算「机器有把握」，界面上不再要求人逐条确认。

第 3 集上量的（当时在全部角色里挑一个）：把握不低于 0.6 的片段占八成，其中 97% 判对；
低于 0.6 的只对了三成多。改成每个目标角色各自判断之后还没有重新量。
"""

FAMILIAR_QUANTILE = 0.05
"""「像不像」的门槛取同角色最近相似度的这个分位。九成五的已确认片段都能过这道门槛。"""

MIN_FAMILIAR_LABELS = 20
"""已确认片段少于这么多时量不出可靠的门槛，这时机器一律不算有把握。"""


@dataclass(frozen=True)
class Guess:
    names: tuple[str, ...]
    """全部目标角色加上「其他」，从最像往下排。"""
    probabilities: tuple[float, ...]
    """目标角色是「是 TA」的概率；「其他」是 1 减去最高的那个。几个数加起来不一定是 1。"""
    similarity: float
    """和最像的目标角色里最像的那条已确认片段的余弦相似度。"""
    familiar: bool | None
    """第一名是目标角色时：相似度过没过门槛，没过就可能是还没见过的人。第一名是「其他」时
    不做这道检查，记成过了。标签太少量不出门槛时是 None。"""

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
    """每条已确认片段和同角色其余片段的最高相似度，取偏低一端的分位。"""
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
    """对声纹表的每一行给出预测。

    `examples` 是目标角色到（正例行号, 反例行号）；`rejects` 是人说过「不是这个角色」的行和角色，
    这些行上那个角色的概率记成 0。
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
            # 还没有反例，分不出谁不是 TA，只能都算像。
            chances[:, k] = 1.0
        else:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(C=STRENGTH, max_iter=3000)
            model.fit(features[positives + negatives], [1] * len(positives) + [0] * len(negatives))
            chances[:, k] = model.predict_proba(features)[:, 1]
        # 每一行和这个角色里最像的那条已确认片段的相似度；已确认片段不和自己比。
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
