"""一个小标注工具，用来破掉循环论证。

**它要解决的问题。** `evaluation/distance.py` 量出来的「同一个人的距离更近」，用的「同一个人」
是切段认人给的标签，不是人工标注。标签本身可能是错的，拿它验证建立在它之上的结论，属于自己
证明自己。所以需要少量人工标注做锚点。

**设计上刻意做的三件事：**

1. **不给你看机器的标签。** 片段打乱、改成匿名编号再放出来，你听到什么就分什么。看见机器的
   答案会让人倾向于点头，那样标出来的东西没有价值。
2. **不问「这是谁」，只问「这几条是不是同一个人」。** 你不需要认识角色，也不用起名，
   把听着像同一个人的丢进同一组就行。这跟决策 9 的顺序一致：先分组，起名是后面的事。
3. **只抽一小部分。** 默认每个机器分组抽 5 条，一集大概三十几条，十几二十分钟能标完。
   目的是验证，不是造训练集。

**标完之后能回答两个问题**：机器分的组纯不纯（每组里是不是真的只有一个人），以及拿人工标签
重算一遍声纹距离，结论跟机器标签算出来的差多少。

工具本身是一个本地网页：起一个只听 localhost 的小服务，音频不出本机。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

PER_SPEAKER = 5
"""每个机器分组抽几条。调大了标得更准，也标得更久。"""

PORT = 8765

SPECIAL = {
    "__unclear__": "听不清",
    "__multiple__": "不止一个人",
    "__not_speech__": "不是说话",
}
"""三个特殊桶。它们不参与「同一个人」的比较，但本身就是有用的信息：
落进「不止一个人」的条数，直接说明音质筛选之后还剩多少脏片段。"""


@dataclass
class Clip:
    """一条待标注的片段。machine 是机器给的标签，**不会发到网页上**。"""

    clip_id: str
    start: float
    end: float
    machine: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Sample:
    """一次标注任务。"""

    clips: list[Clip] = field(default_factory=list)

    def public(self) -> list[dict[str, Any]]:
        """给网页看的版本，机器标签已经摘掉。"""
        return [
            {"id": c.clip_id, "seconds": round(c.duration, 2), "at": round(c.start, 1)}
            for c in self.clips
        ]


def pick_sample(scored: list[dict[str, Any]], per_speaker: int = PER_SPEAKER) -> Sample:
    """按机器分组分层抽样，每组内部沿时间轴均匀取，避免抽到挨在一起的几条。

    挨在一起的两条本来就像，拿它们验证等于放水。抽完打乱顺序，编号重排成匿名的。
    """
    import random
    from collections import defaultdict

    by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        by_speaker[str(item["speaker"])].append(item)

    picked: list[dict[str, Any]] = []
    for speaker in sorted(by_speaker):
        own = sorted(by_speaker[speaker], key=lambda q: q["start"])
        take = min(per_speaker, len(own))
        step = len(own) / take
        picked += [own[int(i * step)] for i in range(take)]

    random.Random(0).shuffle(picked)
    return Sample(
        clips=[
            Clip(
                clip_id=f"clip_{i:02d}",
                start=float(item["start"]),
                end=float(item["end"]),
                machine=str(item["speaker"]),
            )
            for i, item in enumerate(picked)
        ]
    )


def stamp(seconds: float) -> str:
    """秒换成 mm:ss.s，给你在视频里定位用。超过一小时也只显示分钟，动画一集用不上小时。"""
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def by_time(sample: Sample) -> list[dict[str, Any]]:
    """按时间从早到晚排好，带上时间戳。

    **为什么这一版不打乱顺序。** 前两种模式靠耳朵判断，打乱是为了防止「前后两条挨着，
    就默认是同一个人」这种偷懒。但对着画面认人的时候，真答案来自视频而不是音频，
    顺序带不来偏见；反过来，乱序会逼着你在视频里来回拖，那才是真正的成本。
    """
    return [
        {
            "id": c.clip_id,
            "stamp": stamp(c.start),
            "stamp_end": stamp(c.end),
            "seconds": round(c.duration, 1),
        }
        for c in sorted(sample.clips, key=lambda x: x.start)
    ]


PAIR_BINS = 10
PAIR_PER_BIN = 6
PAIR_ANSWERS = {"same": "同一个人", "different": "不同的人", "unsure": "拿不准"}


@dataclass
class Pair:
    """一道两两比对题。machine_same 是机器的看法，**不会发到网页上**。"""

    pair_id: str
    left: str
    right: str
    distance: float
    bucket: int
    machine_same: bool


def pick_pairs(
    meta: list[Any],
    vectors: Any,
    per_bin: int = PAIR_PER_BIN,
    bins: int = PAIR_BINS,
) -> tuple[Sample, list[Pair]]:
    """按声纹距离分档抽配对题，每档抽同样多。

    **为什么按距离分档，而不是随便抽。** 随便抽的话，90 条里有 83% 的组合是不同人，大部分
    题目一听就知道答案，白费力气。按距离均匀铺开，才能量出「人耳觉得是同一个人」的比例
    随距离怎么变，那条曲线穿过 50% 的地方就是我们要的分界线。

    代价要写明白：**这样抽出来的样本不能用来估分离程度**，因为抽样本身就是按模型的看法来的。
    它只能用来定分界线。想估分离程度得另外均匀随机抽。
    """
    import random

    import numpy as np

    distance = 1.0 - vectors @ vectors.T
    rows, cols = np.triu_indices(len(meta), k=1)
    values = distance[rows, cols]
    edges = np.quantile(values, np.linspace(0, 1, bins + 1))

    rng = random.Random(0)
    chosen: list[tuple[int, int, float, int]] = []
    for bucket in range(bins):
        low, high = edges[bucket], edges[bucket + 1]
        inside = np.where((values >= low) & (values <= high))[0]
        if len(inside) == 0:
            continue
        for index in rng.sample(list(inside), min(per_bin, len(inside))):
            chosen.append((int(rows[index]), int(cols[index]), float(values[index]), bucket))

    used = sorted({i for a, b, _, _ in chosen for i in (a, b)})
    clip_id = {index: f"clip_{n:02d}" for n, index in enumerate(used)}
    sample = Sample(
        clips=[
            Clip(
                clip_id=clip_id[index],
                start=float(meta[index].start),
                end=float(meta[index].end),
                machine=str(meta[index].speaker),
            )
            for index in used
        ]
    )

    rng.shuffle(chosen)
    pairs = [
        Pair(
            pair_id=f"pair_{n:02d}",
            left=clip_id[a],
            right=clip_id[b],
            distance=round(dist, 4),
            bucket=bucket,
            machine_same=meta[a].speaker == meta[b].speaker,
        )
        for n, (a, b, dist, bucket) in enumerate(chosen)
    ]
    return sample, pairs


def save_pairs(pairs: list[Pair], path: Path) -> None:
    path.write_text(
        json.dumps([p.__dict__ for p in pairs], ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_pairs(path: Path) -> list[Pair]:
    return [Pair(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def pairs_report(pairs: list[Pair], answers: dict[str, str]) -> dict[str, Any]:
    """量出「人耳觉得是同一个人」的比例随声纹距离怎么变，并读出分界线。

    分界线取那条曲线穿过 50% 的地方，用相邻两档的中点做线性插值。
    """
    from collections import defaultdict

    by_bucket: dict[int, list[Pair]] = defaultdict(list)
    for pair in pairs:
        if answers.get(pair.pair_id) in ("same", "different"):
            by_bucket[pair.bucket].append(pair)

    curve: list[dict[str, Any]] = []
    for bucket in sorted(by_bucket):
        group = by_bucket[bucket]
        same = sum(1 for p in group if answers[p.pair_id] == "same")
        curve.append(
            {
                "bucket": bucket,
                "distance_from": round(min(p.distance for p in group), 3),
                "distance_to": round(max(p.distance for p in group), 3),
                "midpoint": round(sum(p.distance for p in group) / len(group), 3),
                "answered": len(group),
                "said_same": same,
                "rate": round(same / len(group), 3),
            }
        )

    threshold = None
    for earlier, later in pairwise(curve):
        if earlier["rate"] >= 0.5 > later["rate"]:
            span = earlier["rate"] - later["rate"]
            share = (earlier["rate"] - 0.5) / span if span else 0.0
            threshold = round(
                earlier["midpoint"] + share * (later["midpoint"] - earlier["midpoint"]), 4
            )
            break

    answered = [p for p in pairs if answers.get(p.pair_id) in ("same", "different")]
    agree = sum(1 for p in answered if (answers[p.pair_id] == "same") == p.machine_same)
    return {
        "answered": len(answered),
        "unsure": sum(1 for p in pairs if answers.get(p.pair_id) == "unsure"),
        "unanswered": sum(1 for p in pairs if p.pair_id not in answers),
        "curve": curve,
        "threshold": threshold,
        "agrees_with_machine": round(agree / len(answered), 3) if answered else None,
        "note": (
            "配对是按声纹距离分档抽的，所以这份**只能用来定分界线**，"
            "不能用来估分离程度。估分离程度要另外均匀随机抽。"
        ),
    }


def save_sample(sample: Sample, path: Path) -> None:
    """把抽样结果连同机器标签存下来。机器标签只留在这个文件里，不进网页。"""
    path.write_text(
        json.dumps([c.__dict__ for c in sample.clips], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def load_sample(path: Path) -> Sample:
    return Sample(clips=[Clip(**item) for item in json.loads(path.read_text(encoding="utf-8"))])


def export_sample(sample: Sample, vocals: Path, out_dir: Path) -> int:
    """把抽中的片段切出来存成 wav，浏览器能直接放。

    从**原始采样率的人声轨**上切，不是从 16 kHz 分析副本上切。人耳听得出区别，
    而这一步是给人听的。
    """
    import soundfile as sf

    out_dir.mkdir(parents=True, exist_ok=True)
    info = sf.info(str(vocals))
    for clip in sample.clips:
        data, _ = sf.read(
            str(vocals),
            start=int(clip.start * info.samplerate),
            stop=int(clip.end * info.samplerate),
            always_2d=True,
        )
        sf.write(str(out_dir / f"{clip.clip_id}.wav"), data, info.samplerate, subtype="PCM_16")
    return len(sample.clips)


def apply_labels(
    meta: list[Any], labels: dict[str, str], sample: Sample
) -> tuple[list[Any], dict[str, Any]]:
    """把人工标签贴回指纹的元信息上，只保留标过、且不在特殊桶里的片段。

    返回（换成人工标签的元信息, 一份账）。指纹矩阵那边要按同样的下标筛，
    所以这里连下标一起返回。
    """
    from dataclasses import replace

    by_time = {(round(c.start, 3), round(c.end, 3)): c for c in sample.clips}
    kept: list[Any] = []
    indices: list[int] = []
    skipped = {"没标": 0, **{name: 0 for name in SPECIAL.values()}}

    for index, item in enumerate(meta):
        clip = by_time.get((round(item.start, 3), round(item.end, 3)))
        if clip is None:
            continue
        answer = labels.get(clip.clip_id)
        if answer is None:
            skipped["没标"] += 1
            continue
        if answer in SPECIAL:
            skipped[SPECIAL[answer]] += 1
            continue
        kept.append(replace(item, speaker=answer))
        indices.append(index)

    return kept, {"indices": indices, "skipped": skipped}


def purity(sample: Sample, labels: dict[str, str]) -> dict[str, Any]:
    """机器分的每个组里，最多的那个人工标签占多大比例。

    这是使用者最关心的数字：如果一个组里 90% 真的是同一个人，那它基本能用。
    特殊桶的条数单独列，因为「不止一个人」本身就说明这条片段不合格。
    """
    from collections import Counter, defaultdict

    grouped: dict[str, list[str]] = defaultdict(list)
    for clip in sample.clips:
        answer = labels.get(clip.clip_id)
        if answer is not None:
            grouped[clip.machine].append(answer)

    groups: dict[str, Any] = {}
    clean_total = clean_hit = 0
    informative = 0
    for machine in sorted(grouped):
        answers = grouped[machine]
        clean = [a for a in answers if a not in SPECIAL]
        top = Counter(clean).most_common(1)
        # 只有 0 或 1 条能用的组算不出纯度：一条的纯度必然是 1.0，等于白送。
        # 这种组不进整体统计，否则整体值会被一堆 1.0 抬上去，看着好看其实没信息。
        tells_us_something = len(clean) >= 2
        groups[machine] = {
            "labeled": len(answers),
            "usable": len(clean),
            "dominant": top[0][0] if top else None,
            "purity": round(top[0][1] / len(clean), 3) if tells_us_something else None,
            "informative": tells_us_something,
            "special": {SPECIAL[a]: answers.count(a) for a in SPECIAL if a in answers},
        }
        if tells_us_something:
            informative += 1
            clean_total += len(clean)
            clean_hit += top[0][1]

    return {
        "groups": groups,
        "informative_groups": informative,
        "overall_purity": round(clean_hit / clean_total, 3) if clean_total else None,
        "note": (
            "整体纯度只统计「有 2 条以上能用」的组。只剩 1 条的组纯度必然是 1.0，"
            "把它们算进来会把整体值虚高，所以排除掉，并在 informative 里标出来。"
        ),
    }
