"""把片段按人归到一起，跨集也连上。

**分两层做，不要把所有片段一次性丢进去分组**（决策 8，`HOW_IT_WORKS.md` 4.5）：

1. **第一层**：在一集内部，拿我们自己的声音指纹把片段聚一遍。
2. **第二层**：每个第一层的组取它所有片段指纹的平均（按时长加权）当中心点，再把全系列
   所有中心点合并。

分两层的原因是**一个中心点比单条片段稳得多** —— 它是几十秒语音的平均，而单条片段只有一两秒。
顺带把计算量从「片段数的平方」降到「组数的平方」。

**第一层原本直接用切段认人给的分组，实测不行，2026-09-06 改掉了**（决策 24）。pyannote 的
分组在第 2 集上 clip 级纯度只有 0.76：`SPEAKER_10` 是 5 条片段 5 个不同角色。一个组里塞了
5 个人，它的中心点就没有意义，上面那句「中心点比单条片段稳」的前提直接不成立。

现在的做法是**只用 pyannote 切段，不用它判断「这段是谁」**。拿两集 75 条人工看画面的标注量：

| 第一层怎么做 | 分组好坏分 |
| --- | --- |
| 用 pyannote 的分组 | 0.733 |
| **自己的指纹重聚一遍** | **0.930** |

**它仍然修不了「两个角色被并成一组」那一类**，那得靠人工拆分（4.6）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOCAL_THRESHOLD = 0.55
"""第一层的分界线：一集之内，两条**片段**的指纹距离小于它才聚到一起。

比 `HOW_IT_WORKS.md` 4.5 那个 0.6（片段级的等错误率分界线）略紧一点，因为这里用的是平均
连接 —— 合并看的是两堆之间的平均距离，比一对一判断更容易合，所以门槛要相应收一点。

**第一层宁可切碎也不要合错。** 切碎了第二层会合回来，合错了后面没有任何一步能拆开。
"""

THRESHOLD = 0.25
"""第二层的分界线：两个**中心点**的距离小于它才算同一个人。

**最容易在这里犯的错：拿片段级的分界线来比中心点。** 4.5 那个 0.6 量的是**单条片段之间**的
距离。中心点是几十条片段的平均，**天然比单条片段互相更近** —— 平均会把向量往中间拉。同一个
数字搬过来会松得离谱：实测拿 0.6 分，23 个组塌成 2 个人，而且程序不报错。

**两层的分界线一起扫出来的**，用两集 75 条人工看画面的标注，分数是分组好坏分（同时惩罚
「该合的没合」和「该分的没分」）：

| 第一层 \\ 第二层 | 0.20 | 0.25 | 0.30 | 0.35 | 0.40 |
| --- | --- | --- | --- | --- | --- |
| 0.45 | 0.852 | 0.852 | 0.837 | 0.842 | 0.846 |
| 0.50 | 0.917 | 0.898 | 0.911 | 0.884 | 0.884 |
| **0.55** | 0.930 | **0.930** | 0.921 | 0.904 | 0.863 |
| 0.60 | 0.930 | 0.920 | 0.912 | 0.912 | 0.840 |
| 0.65 | 0.848 | 0.848 | 0.848 | 0.848 | 0.802 |

第一层 0.55 到 0.60、第二层 0.20 到 0.30 是一整片平台（0.912 到 0.930），**不是一个尖峰**，
取中间的 0.55 / 0.25。作为对照，第一层直接用 pyannote 的分组只有 0.733。

**只有两集、75 条、3 个跨集出现的角色。** 平台很宽所以这两个数是稳的，但「0.25 而不是 0.22」
这种精度撑不住，换作品要重新扫一遍这张表。
"""

MISC_SECONDS = 60.0
"""总时长不到这么久的组，全部并进 `_misc`，不去费劲区分（决策 10）。

一部动画有 5 到 15 个常驻角色，外加大量只有一两句台词的路人。路人的两句话没有收集价值，
而试图区分它们会明显拖累效果和你的复核工作量。
"""


@dataclass(frozen=True)
class Clip:
    """一条片段，带着它是从哪一集来的。

    `local` 是第一层聚出来的组号，`machine` 是切段认人原本给的标签。**后者只用来回溯**，
    不参与任何判断 —— 实测它一个组里能塞进 5 个不同角色（决策 24）。
    """

    episode: str
    local: str
    start: float
    end: float
    machine: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Group:
    """第一层聚出来的一个组，是第二层合并的最小单位。

    `rows` 是这些片段在指纹矩阵里的行号，算中心点时要用。
    """

    episode: str
    local: str
    clips: list[Clip] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(c.duration for c in self.clips)


def refine(vectors: Any, threshold: float = LOCAL_THRESHOLD) -> Any:
    """第一层：一集之内，拿指纹把片段重聚一遍，不用切段认人给的答案。

    **为什么不直接用它给的答案**：实测第 2 集 13 个机器分组的 clip 级纯度只有 0.76，
    其中一个组是 5 条片段 5 个不同角色。中心点是组内片段的平均，组本身不纯，中心点就没有
    意义。改成自己聚之后，两集 75 条标注上的分组好坏分从 0.733 升到 0.930（决策 24）。

    切段认人的结果仍然有用 —— 我们用它**切**在哪儿，只是不用它判断**是谁**。
    """
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    return AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    ).fit_predict(vectors)


def collect(
    runs: list[tuple[str, list[Any], Any]], local_threshold: float = LOCAL_THRESHOLD
) -> list[Group]:
    """跑第一层，把各集的片段归堆。

    `runs` 每项是（集名, 指纹元信息列表, 指纹矩阵），元信息和矩阵的行号一一对应。
    """
    groups: dict[tuple[str, str], Group] = {}
    for episode, meta, vectors in runs:
        labels = refine(vectors, local_threshold)
        for row, item in enumerate(meta):
            local = f"c{int(labels[row]):03d}"
            key = (episode, local)
            if key not in groups:
                groups[key] = Group(episode=episode, local=local)
            groups[key].clips.append(
                Clip(
                    episode=episode,
                    local=local,
                    start=float(item.start),
                    end=float(item.end),
                    machine=str(item.speaker),
                )
            )
            groups[key].rows.append(row)
    return sorted(groups.values(), key=lambda g: (g.episode, g.local))


def centroids(groups: list[Group], runs: list[tuple[str, list[Any], Any]]) -> Any:
    """每个组算一个中心点：组内所有片段指纹的加权平均，权重是时长。

    **按时长加权**，因为长片段的指纹更可靠。算完重新归一化长度，这样两个中心点点乘
    仍然是余弦相似度。
    """
    import numpy as np

    matrices = {episode: vectors for episode, _, vectors in runs}

    out = []
    for group in groups:
        weights = np.array([c.duration for c in group.clips])
        centre = np.average(matrices[group.episode][group.rows], axis=0, weights=weights)
        norm = float(np.linalg.norm(centre))
        out.append(centre / norm if norm else centre)
    return np.stack(out)


def link(points: Any, threshold: float = THRESHOLD) -> Any:
    """第二层：把中心点合并成跨集的人。返回每个中心点属于第几号人。

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
        machines = sorted({f"{c.episode}/{c.machine}" for c in clips if c.machine})
        rows.append(
            {
                "name": name,
                "clips": len(clips),
                "total_sec": round(sum(c.duration for c in clips), 1),
                "episodes": episodes,
                "from_groups": locals_,
                "from_machine_groups": machines,
            }
        )
    rows.sort(key=lambda r: (r["name"] == "_misc", -float(str(r["total_sec"]))))
    return {
        "groups_in": len(groups),
        "speakers_out": sum(1 for r in rows if r["name"] != "_misc"),
        "speakers": rows,
    }
