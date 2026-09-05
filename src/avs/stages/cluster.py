"""把片段按人归到一起，跨集也连上。

**分两层做，不要把所有片段一次性丢进去分组**（决策 8，`HOW_IT_WORKS.md` 4.5）：

1. **第一层**是切段认人已经给的：一集内部，每条片段属于哪个机器分组。
2. **第二层**在这里：每个机器分组取它所有片段指纹的平均（按时长加权）当中心点，再把全系列
   所有中心点合并。

分两层的原因是**一个中心点比单条片段稳得多** —— 它是几十秒语音的平均，而单条片段只有一两秒。
顺带把计算量从「片段数的平方」降到「组数的平方」。

**它顺手修了切段认人的两类错。** 实测（`STATUS.md`）：同一个角色会被切段认人拆成好几个组
（第 1 集的 teo 被拆进三个组，还是同一集之内），两个角色也会被并成一组。第二层合并的是
中心点，不管它们来自哪一集，所以**同一集内被拆开的组也会在这里被并回去**。合不回来的那类
（两个人被并成一组）这一步管不了，得靠人工拆分（4.6）。

**分界线取多少**：`HOW_IT_WORKS.md` 4.5 说这是「整个工具最关键、也最难凭空定的一个数字」。
现在有两集独立的实测：第 1 集 0.59、第 2 集 0.63，所以默认取 0.6。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

THRESHOLD = 0.4
"""合并的分界线，中心点之间的距离小于它才算同一个人。距离是 1 减余弦相似度。

**最容易在这里犯的错：拿片段级的分界线来比中心点。** `STATUS.md` 和 `HOW_IT_WORKS.md` 4.5
里那个 0.6（第 1 集 0.59、第 2 集 0.63）量的是**单条片段之间**的距离。这里比的是**中心点**，
而中心点是几十条片段的平均，**天然比单条片段互相更近** —— 平均会把向量往中间拉。所以同一个
数字搬过来会松得离谱：实测拿 0.6 分，23 个机器分组塌成 2 个人。

**中心点该用多少，单独量过。** 拿第 2 集 46 条人工看画面的标注，给 13 个机器分组各定出真名字，
再看中心点两两之间的距离：

| | 对数 | 中位数 | 边界 |
| --- | --- | --- | --- |
| 同一个人 | 4 | 0.245 | 最大 **0.358** |
| 不同的人 | 74 | 0.747 | 最小 **0.378** |

**两边完全没有重叠**，中间有一道 0.358 到 0.378 的缝。分界线取多少对结果的影响：

| 分界线 | 合并成几个人 | 纯度 |
| --- | --- | --- |
| 0.30 | 11 | 1.00 |
| **0.35 到 0.45** | **10（真答案就是 10）** | **1.00** |
| 0.50 | 9 | 0.92 |
| 0.60 | 6 | 0.69 |

0.35 到 0.45 是一整片平台，取中间的 0.4。

**这个数比片段级那个薄得多**：同一个人的中心点对只有 4 对，而且只有一集。两边分得开是真的，
但「0.4 而不是 0.37 或 0.43」这个精度撑不住，换一集或换作品都要重新量。
"""

MISC_SECONDS = 60.0
"""总时长不到这么久的组，全部并进 `_misc`，不去费劲区分（决策 10）。

一部动画有 5 到 15 个常驻角色，外加大量只有一两句台词的路人。路人的两句话没有收集价值，
而试图区分它们会明显拖累效果和你的复核工作量。
"""


@dataclass(frozen=True)
class Clip:
    """一条片段，带着它是从哪一集来的。"""

    episode: str
    local: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Group:
    """一个机器分组（某一集内部的），是第二层合并的最小单位。"""

    episode: str
    local: str
    clips: list[Clip] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(c.duration for c in self.clips)


def collect(runs: list[tuple[str, list[Any], Any]]) -> list[Group]:
    """把各集的片段按「哪一集的哪个机器分组」归堆。

    `runs` 每项是（集名, 指纹元信息列表, 指纹矩阵），元信息和矩阵的行号一一对应。
    """
    groups: dict[tuple[str, str], Group] = {}
    for episode, meta, _ in runs:
        for item in meta:
            key = (episode, str(item.speaker))
            if key not in groups:
                groups[key] = Group(episode=episode, local=str(item.speaker))
            groups[key].clips.append(
                Clip(
                    episode=episode,
                    local=str(item.speaker),
                    start=float(item.start),
                    end=float(item.end),
                )
            )
    return sorted(groups.values(), key=lambda g: (g.episode, g.local))


def centroids(groups: list[Group], runs: list[tuple[str, list[Any], Any]]) -> Any:
    """每个组算一个中心点：组内所有片段指纹的加权平均，权重是时长。

    **按时长加权**，因为长片段的指纹更可靠。算完重新归一化长度，这样两个中心点点乘
    仍然是余弦相似度。
    """
    import numpy as np

    index: dict[tuple[str, str], list[tuple[float, Any]]] = {}
    for episode, meta, vectors in runs:
        for row, item in enumerate(meta):
            key = (episode, str(item.speaker))
            index.setdefault(key, []).append((float(item.end) - float(item.start), vectors[row]))

    out = []
    for group in groups:
        weights, stack = zip(*index[(group.episode, group.local)], strict=True)
        centre = np.average(np.stack(stack), axis=0, weights=np.array(weights))
        norm = float(np.linalg.norm(centre))
        out.append(centre / norm if norm else centre)
    return np.stack(out)


def link(points: Any, threshold: float = THRESHOLD) -> Any:
    """把中心点合并成跨集的人。返回每个中心点属于第几号人。

    用层次聚类的平均连接：两堆之间的距离取「所有跨堆配对的平均距离」，小于分界线就合并。
    **不指定分成几组**，因为事先不知道有几个人 —— 这正是 4.5 说的那件事。

    取平均连接而不是最近或最远：最近连接容易被一对偶然很像的片段串成一大堆，最远连接
    则会因为一对偶然不像的把同一个人拆开。
    """
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    if len(points) == 1:
        return np.zeros(1, dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    )
    return model.fit_predict(points)


def assign(
    groups: list[Group], labels: Any, misc_seconds: float = MISC_SECONDS
) -> dict[str, list[Clip]]:
    """按合并结果把片段归到最终的组里，太小的并进 `_misc`。

    正式的组按总时长从多到少编号，`speaker_01` 是素材最多的那个。
    """
    from collections import defaultdict

    buckets: dict[int, list[Clip]] = defaultdict(list)
    for group, label in zip(groups, labels, strict=True):
        buckets[int(label)].extend(group.clips)

    ranked = sorted(buckets.values(), key=lambda cs: -sum(c.duration for c in cs))
    out: dict[str, list[Clip]] = {}
    misc: list[Clip] = []
    number = 0
    for clips in ranked:
        if sum(c.duration for c in clips) < misc_seconds:
            misc.extend(clips)
            continue
        number += 1
        out[f"speaker_{number:02d}"] = sorted(clips, key=lambda c: (c.episode, c.start))
    if misc:
        out["_misc"] = sorted(misc, key=lambda c: (c.episode, c.start))
    return out


def summarize(assigned: dict[str, list[Clip]], groups: list[Group]) -> dict[str, Any]:
    """分完之后每组有多少料，以及它是由哪些集的哪些机器分组拼起来的。"""
    rows = []
    for name, clips in assigned.items():
        episodes = sorted({c.episode for c in clips})
        locals_ = sorted({f"{c.episode}/{c.local}" for c in clips})
        rows.append(
            {
                "name": name,
                "clips": len(clips),
                "total_sec": round(sum(c.duration for c in clips), 1),
                "episodes": episodes,
                "from_groups": locals_,
            }
        )
    rows.sort(key=lambda r: (r["name"] == "_misc", -float(str(r["total_sec"]))))
    return {
        "groups_in": len(groups),
        "speakers_out": sum(1 for r in rows if r["name"] != "_misc"),
        "speakers": rows,
    }
