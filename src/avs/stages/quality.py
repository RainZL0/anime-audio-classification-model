"""按音质给候选片段打分，然后严格筛。只求准，不求全。

这一步在流程里的位置是**靠前**的，不是最后的收尾环节，理由见决策 15。简单说：先筛掉脏的，
后面算指纹和分组都建立在干净数据上，而且我们只需要主角的素材，本来就承受得起低留存率。

**它能做什么、不能做什么，都验证过**（第 1 集，拿 7 条人工标注的不合格片段检验）：

| 人工判断 | 音质分排名（1 = 最差） | 抓到了吗 |
| --- | --- | --- |
| 先一人后一群人 | 前 3% | 抓到 |
| 多人呼喊 | 前 6% | 抓到 |
| 混乱不纯净 | 前 7% | 抓到 |
| 两人重叠 | 前 10% | 抓到 |
| 两个人同时出声 | 前 44% | **抓不到** |
| 先后两个人 | 前 52% | **抓不到** |

规律是：**掺了群众声和杂音的能抓住，两个清晰人声的抓不住**，因为后者音质本来就好。所以别
指望这一步解决「一条里有两个清晰的人」，那是另一族问题，目前还没有可用手段。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEEP_RATIO = 0.5
"""默认保留音质最好的这个比例。

第 1 集实测：保留 50% 剩 301 秒，折算整季 13 集约 65 分钟，最大的说话人约 23 分钟。
收音色一个角色 10 到 30 分钟就够，所以这个留存率对主角是够的。想更保守就调低。
"""

MIN_SECONDS = 0.5
"""短于这个长度的片段打分不可靠，直接跳过，单位秒。"""


@dataclass(frozen=True)
class Quality:
    """一条片段的音质。score 是三项指标的百分位排名取平均，0 到 1，越大越好。"""

    speaker: str
    start: float
    end: float
    stoi: float
    pesq: float
    sisdr: float
    score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


def score_segments(wav: Path, segments: list[Any], device: str = "cuda") -> list[Quality]:
    """给每条片段打音质分。wav 要 16 kHz 单声道，也就是分析副本。

    用 torchaudio 自带的 SQUIM，不需要额外授权，也不用联网拿模型以外的东西。它给的是
    「无参考版」的 STOI、PESQ、SI-SDR 估计值，三项各自的绝对值不必深究，我们只用排名。
    """
    import soundfile as sf
    import torch
    import torchaudio.pipelines as pipelines

    model = pipelines.SQUIM_OBJECTIVE.get_model().to(device).eval()
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    mono = samples[:, 0]

    raw: list[Quality] = []
    with torch.no_grad():
        for seg in segments:
            start, end = float(seg.start), float(seg.end)
            chunk = mono[int(start * sample_rate) : int(end * sample_rate)]
            if len(chunk) < MIN_SECONDS * sample_rate:
                continue
            wave = torch.from_numpy(chunk).unsqueeze(0).to(device)
            stoi, pesq, sisdr = (float(x[0]) for x in model(wave))
            raw.append(
                Quality(
                    speaker=str(seg.speaker),
                    start=start,
                    end=end,
                    stoi=round(stoi, 4),
                    pesq=round(pesq, 3),
                    sisdr=round(sisdr, 2),
                )
            )
    return _add_composite(raw)


def _add_composite(scored: list[Quality]) -> list[Quality]:
    """三项指标各自换算成百分位排名再取平均。

    用排名而不是绝对值，是因为三项的量纲完全不同（STOI 是 0 到 1，SI-SDR 是分贝），直接
    加权没有意义。代价是这个分数只在一批片段内部可比，换一集要重新算。
    """
    if len(scored) < 2:
        return scored

    ranks: dict[int, float] = dict.fromkeys(range(len(scored)), 0.0)
    for key in ("stoi", "pesq", "sisdr"):
        order = sorted(range(len(scored)), key=lambda i: getattr(scored[i], key))
        for position, index in enumerate(order):
            ranks[index] += position / (len(scored) - 1)

    return [
        Quality(
            speaker=q.speaker,
            start=q.start,
            end=q.end,
            stoi=q.stoi,
            pesq=q.pesq,
            sisdr=q.sisdr,
            score=round(ranks[i] / 3, 4),
        )
        for i, q in enumerate(scored)
    ]


def keep_best(
    scored: list[Quality], keep_ratio: float = KEEP_RATIO
) -> tuple[list[Quality], list[Quality]]:
    """留下音质最好的一部分，其余淘汰。返回 (留下的, 淘汰的)。

    淘汰的也带回去，不要直接丢：万一比例定错了能捞回来，这是 HOW_IT_WORKS 4.7 的规矩。
    """
    ordered = sorted(scored, key=lambda q: -q.score)
    cut = max(1, int(len(ordered) * keep_ratio)) if ordered else 0
    return ordered[:cut], ordered[cut:]


def summarize(kept: list[Quality], rejected: list[Quality]) -> dict[str, Any]:
    """筛完还剩多少料，按说话人分。"""
    from collections import defaultdict

    per: dict[str, list[float]] = defaultdict(list)
    for q in kept:
        per[q.speaker].append(q.duration)

    speakers: list[dict[str, Any]] = [
        {"speaker": name, "segments": len(v), "total_sec": round(sum(v), 1)}
        for name, v in per.items()
    ]
    speakers.sort(key=lambda row: float(row["total_sec"]), reverse=True)

    return {
        "kept": len(kept),
        "rejected": len(rejected),
        "kept_sec": round(sum(q.duration for q in kept), 1),
        "rejected_sec": round(sum(q.duration for q in rejected), 1),
        "speakers": speakers,
    }
