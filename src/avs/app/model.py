"""在人工标签上训练小分类器，给每条有声纹的片段排出最像的几个角色。

做法和 evaluation/classify.py 里的「小分类器」一样，是逻辑回归。训练集只有几百到几千条，
一次训练不到一秒，所以每改一条标签都整个重训，不做增量更新。

**分类器只会在认识的角色里挑。** 只标了两个角色时，旁白也会被硬说成其中一个，而且概率
还不低。所以另加一道「像不像」的检查：这句和它被归给的角色里最像的那一条已确认片段，
相似度要够高。够高的标准不写死，从当前的人工标签里量：每条已确认片段和同角色其余片段
最像的那个相似度，取其中偏低的一端（第 `FAMILIAR_QUANTILE` 分位）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STRENGTH = 100.0
"""逻辑回归的正则强度。第 1、2 集互相留出时挑出来的值在 30 到 1000 之间，取中间。"""

AUTO_CONFIDENCE = 0.6
"""把握到这个数就算「机器有把握」，界面上不再要求人逐条确认。

第 3 集上量的：把握不低于 0.6 的片段占八成，其中 97% 判对；低于 0.6 的只对了三成多。
"""

FAMILIAR_QUANTILE = 0.05
"""「像不像」的门槛取同角色最近相似度的这个分位。九成五的已确认片段都能过这道门槛。"""

MIN_FAMILIAR_LABELS = 20
"""已确认片段少于这么多时量不出可靠的门槛，这时机器一律不算有把握。"""

TOP = 3


@dataclass(frozen=True)
class Guess:
    names: tuple[str, ...]
    """最像的几个角色，从最像往下排。"""
    probabilities: tuple[float, ...]
    similarity: float
    """和第一个角色里最像的那条已确认片段的余弦相似度。"""
    familiar: bool | None
    """相似度过了门槛。没过就可能是还没见过的角色；标签太少量不出门槛时是 None。"""

    @property
    def confidence(self) -> float:
        return self.probabilities[0]


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
    labeled_rows: list[int],
    names: list[str],
    rejects: dict[int, set[str]],
) -> Trained:
    """对声纹表的每一行给出预测。`rejects` 是人说过「不是这个角色」的行和角色。"""
    import numpy as np

    roles = sorted(set(names))
    if not roles or len(features) == 0:
        return Trained({}, None)
    if len(roles) == 1:
        probabilities = np.ones((len(features), 1))
    else:
        from sklearn.linear_model import LogisticRegression

        model = LogisticRegression(C=STRENGTH, max_iter=3000)
        model.fit(features[labeled_rows], [roles.index(n) for n in names])
        probabilities = np.zeros((len(features), len(roles)))
        probabilities[:, model.classes_] = model.predict_proba(features)

    # 每一行和每个角色里最像的那条已确认片段的相似度；已确认片段不和自己比。
    similarity = features @ features[labeled_rows].T
    similarity[labeled_rows, np.arange(len(labeled_rows))] = -np.inf
    index = np.array([roles.index(n) for n in names])
    nearest = np.full((len(features), len(roles)), -1.0)
    for k in range(len(roles)):
        nearest[:, k] = similarity[:, index == k].max(axis=1)
    threshold = familiar_threshold(features, labeled_rows, names)

    guesses = {}
    for row in range(len(features)):
        own = probabilities[row].copy()
        for name in rejects.get(row, ()):
            if name in roles:
                own[roles.index(name)] = 0.0
        order = np.argsort(-own)[:TOP]
        # 只有一条已确认片段的角色，那条自己和本角色比不出相似度，记成最低的 -1。
        close = max(float(nearest[row, order[0]]), -1.0)
        guesses[row] = Guess(
            names=tuple(roles[k] for k in order),
            probabilities=tuple(round(float(own[k]), 4) for k in order),
            similarity=round(close, 4),
            familiar=None if threshold is None else close >= threshold,
        )
    return Trained(guesses, threshold)
