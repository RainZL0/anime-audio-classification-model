"""试几种办法自动认出「这条片段里不止一个人」，拿人工标注当尺子量它们准不准。

**为什么这是当前最该做的事。** `STATUS.md` 记着：音质筛选留下的前 50% 里，仍有 26% 的片段
有多个人在说话，这是卡住产量的真瓶颈。已知 pyannote 看不见这些声音，SQUIM 也只抓得住掺
群众声那一族。现在第一次有了真尺子 —— `annotations/ep01_v4.json` 里 9 条人工确认「不止一
个人」、25 条人工确认单人，所以候选办法第一次能被量出来。

**先说一个必须知道的陷阱：片段有多长，本身就能猜出答案。** 9 条多人片段全都长于 2.6 秒，
而单人片段的中位数只有 2.2 秒。光看时长就能拿到 0.84 的分得开程度。所以任何候选办法都得
跟「只看时长」比，比不过就没有价值；下面每个办法都会同时给一个**时长配平**的分数，那是只
拿长度接近的一多一单去比，把这个便宜信号扣掉之后剩下的真本事。

三个候选：

| 代号 | 是什么 | 由来 |
| --- | --- | --- |
| `duration` | 片段有多长 | 免费的对照组，不是真办法 |
| `squim` | 音质分（决策 15 在用的） | 已知抓得住群众声那一族，抓不住两个清晰人声 |
| `aesthetics` | Meta 的 Audiobox-Aesthetics 四项分 | 决策 16 记下的候选，一直缺尺子没验 |
| `selfsim` | 片段内部的声纹一不一致 | 失败过一次，这次换了模型和标签重试，见下 |

**`selfsim` 是重试，上一次失败了。** 之前用弱得多的指纹模型、排名又来自循环论证的标签，
7 条已知不合格的排名散在 28% 到 94%，代码删掉了。现在指纹模型的声纹错误率是 7%、标签是
人对着画面标的，条件不一样，所以值得再验一次。**这里不复用上次的任何数字，全部从头算。**
它可能再次失败，那样的话这条路就可以永久关掉了。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

MULTIPLE = "__multiple__"
"""人工标注里表示「这条不止一个人」的值，见 `annotations/README.md`。"""

NOT_A_NAME = {MULTIPLE, "__unclear__", "__not_speech__"}

MATCH_RATIO = 1.5
"""时长配平时，两条片段的长度比不超过这个数才算「长度接近」，可以拿来比。"""

WINDOW_MIN = 0.75
WINDOW_MAX = 1.5
"""`selfsim` 的窗口长度上下限，单位秒。

窗口要够长指纹才可靠（`embeddings/extract.py` 说短于 1 秒就不可靠了），又要够短才能在一条
2 秒多的片段里放下三个窗口看出变化。所以按片段长度的三分之一取，再夹到这个区间里。
短片段的指纹本来就飘，这是这个办法在短片段上的先天限制，不是实现问题。
"""


@dataclass(frozen=True)
class Truth:
    """一条有人工答案的片段。`is_multiple` 就是要检测的那件事。"""

    start: float
    end: float
    name: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def is_multiple(self) -> bool:
        return self.name == MULTIPLE


def load_truth(annotation: Path) -> list[Truth]:
    """读人工标注，只留下答案明确的条目。

    「听不清」和「不是说话」两种都扔掉：它们既不能算多人也不能算单人，留着只会污染分数。
    """
    import json

    clips = json.loads(annotation.read_text(encoding="utf-8"))["clips"]
    return [
        Truth(start=float(c["start"]), end=float(c["end"]), name=str(c["name"]))
        for c in clips
        if c.get("name") and (c["name"] == MULTIPLE or c["name"] not in NOT_A_NAME)
    ]


def _auc(scores: Any, is_multiple: Any) -> float:
    """随便挑一条多人的和一条单人的，多人那条分数确实更高的概率。0.5 等于瞎猜。"""
    import numpy as np

    pos = np.asarray(scores)[is_multiple]
    neg = np.asarray(scores)[~np.asarray(is_multiple)]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    gt = pos[:, None] > neg[None, :]
    tie = pos[:, None] == neg[None, :]
    return float(gt.mean() + 0.5 * tie.mean())


def _auc_length_matched(scores: Any, is_multiple: Any, durations: Any) -> tuple[float, int]:
    """同样的比法，但只比长度接近的一多一单，把「长的多半是多人」这个便宜信号扣掉。

    返回（分数, 参与比较的对数）。对数太少的话这个分数别当真。
    """
    import numpy as np

    scores = np.asarray(scores)
    durations = np.asarray(durations)
    flag = np.asarray(is_multiple)

    wins = 0.0
    pairs = 0
    for i in np.flatnonzero(flag):
        for j in np.flatnonzero(~flag):
            long, short = max(durations[i], durations[j]), min(durations[i], durations[j])
            if short <= 0 or long / short > MATCH_RATIO:
                continue
            pairs += 1
            if scores[i] > scores[j]:
                wins += 1.0
            elif scores[i] == scores[j]:
                wins += 0.5
    return (wins / pairs if pairs else float("nan")), pairs


RESAMPLES = 4000
"""重抽多少次来估「这个分数有多不牢靠」。4000 次几秒钟就跑完，够用了。"""


def _shaky(scores: Any, is_multiple: Any, durations: Any) -> dict[str, Any]:
    """量一下时长配平那个分数有多不牢靠。

    **为什么非做不可**：这把尺子只有 9 条多人片段。换 9 条别的，分数可能完全不一样。做法是
    把手上的片段有放回地重抽很多遍，每遍重算一次分数，看这些分数散得多开。

    返回的 `above_chance` 是「重抽出来的分数高于 0.5 的比例」。它接近 1 才说明这个办法真的
    看见了什么；只要还有相当一部分重抽掉到 0.5 以下，就得说「还看不出来」。
    """
    import numpy as np

    rng = np.random.default_rng(0)
    positive = np.flatnonzero(is_multiple)
    negative = np.flatnonzero(~np.asarray(is_multiple))
    if len(positive) == 0 or len(negative) == 0:
        return {"low": None, "high": None, "above_chance": None}

    draws = []
    for _ in range(RESAMPLES):
        picked = np.concatenate(
            [rng.choice(positive, len(positive)), rng.choice(negative, len(negative))]
        )
        value, pairs = _auc_length_matched(
            np.asarray(scores)[picked],
            np.asarray(is_multiple)[picked],
            np.asarray(durations)[picked],
        )
        if pairs >= 10:
            draws.append(value)
    if len(draws) < RESAMPLES // 10:
        return {"low": None, "high": None, "above_chance": None}

    spread = np.array(draws)
    return {
        "low": round(float(np.percentile(spread, 2.5)), 4),
        "high": round(float(np.percentile(spread, 97.5)), 4),
        "above_chance": round(float((spread > 0.5).mean()), 4),
    }


def _catch_rate(scores: Any, is_multiple: Any, cut_ratio: float) -> float:
    """按这个办法砍掉分数最高的一部分，能砍掉多少条多人片段。

    这是实际用法下的成绩：我们要的是一个筛子，不是一个排序器。
    """
    import numpy as np

    scores = np.asarray(scores)
    flag = np.asarray(is_multiple)
    cut = max(1, round(len(scores) * cut_ratio))
    doomed = np.argsort(-scores)[:cut]
    caught = int(flag[doomed].sum())
    return round(caught / int(flag.sum()), 4) if flag.sum() else float("nan")


def evaluate(name: str, scores: dict[int, float], truth: list[Truth]) -> dict[str, Any]:
    """量一个候选办法。`scores` 是「片段序号 -> 分数」，分数越高越像是多人片段。

    允许缺项：算不出分的片段（比如太短放不下窗口）直接不参与，但会记下少了多少条。
    """
    import numpy as np

    index = sorted(scores)
    kept = [truth[i] for i in index]
    values = np.array([scores[i] for i in index], dtype=np.float64)
    flag = np.array([t.is_multiple for t in kept])
    durations = np.array([t.duration for t in kept])

    matched, pairs = _auc_length_matched(values, flag, durations)
    return {
        "detector": name,
        "scored": len(index),
        "skipped": len(truth) - len(index),
        "multiple": int(flag.sum()),
        "single": int((~flag).sum()),
        "auc": round(_auc(values, flag), 4),
        "auc_length_matched": None if np.isnan(matched) else round(matched, 4),
        "matched_pairs": pairs,
        "shaky": _shaky(values, flag, durations),
        "catch_at_25": _catch_rate(values, flag, 0.25),
        "catch_at_50": _catch_rate(values, flag, 0.5),
    }


def format_report(rows: list[dict[str, Any]]) -> str:
    """把几个候选压成一张能一眼看懂的表。"""
    lines = [
        "  办法              分得开  时长配平（重抽后 95% 落在哪）  砍掉最高 50% 能抓到  条数",
    ]
    for row in rows:
        matched = row["auc_length_matched"]
        shaky = row["shaky"]
        band = (
            " " * 18 if shaky["low"] is None else f"（{shaky['low']:.2f} 到 {shaky['high']:.2f}）"
        )
        lines.append(
            f"  {row['detector']:<16}  {row['auc']:.3f}"
            f"   {'  --  ' if matched is None else f'{matched:.3f}'}  {band}"
            f"       {row['catch_at_50']:>6.0%}"
            f"           {row['scored']}"
            + (f"（少 {row['skipped']} 条）" if row["skipped"] else "")
        )
    lines += [
        "",
        "  分得开 0.5 等于瞎猜。**先看时长配平那一列**：多人片段普遍更长，光看时长就能拿到",
        "  0.84 的分得开，那不是本事。只有在长度接近的片段之间还分得开，才算真的看见了什么。",
        "  括号是把片段重抽几千遍得到的范围，跨过 0.5 就说明这个数字还不牢靠。",
    ]
    return "\n".join(lines)
