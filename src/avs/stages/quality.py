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

**这个数试着放宽到 0.7，被盲测否掉了，退回 0.5**（2026-09-06，决策 21 和 24）。留档是因为
放宽的理由本身没错，错的是「音质分能替耳朵把关」这个假设。

放宽的理由：按音质分排名，每一成的中位数，两集是同一个形状，悬崖在 70% 到 80% 之间 ——

| 保留到 | 第 1 集 sisdr / pesq | 第 2 集 sisdr / pesq |
| --- | --- | --- |
| 50% | 16.1 / 2.58 | 20.2 / 2.80 |
| 70% | 9.8 / 1.87 | 13.9 / 2.34 |
| 80% | 5.8 / 1.59 | 10.1 / 1.86 |

否掉它的证据：24 条盲测（12 条来自 50% 以内、12 条来自新放宽的 50 到 70%，打乱），人工听出
两条不干净，**两条全在新放宽那一段**，50% 以内 12 条一条都没有。脏的形式是走路音效和别人的
语气词 —— **音质分对这两种都没有分辨力**，那两条恰好还排在全集 51% 和 53%，也就是新那批里
最好的位置。所以收紧到 0.6 也没用，只会留着它们、扔掉下面 10 条干净的。
"""

MIN_STOI = 0.85
MIN_PESQ = 1.5
MIN_SISDR = 5.0
"""绝对下限，三项都要过。单位分别是无量纲、无量纲、分贝。

**这是兜底，不是主力。** 上面那个比例是相对的：一集整体都很差时，它照样留下最好的 70%，
哪怕那 70% 全是废的。决策 15 当时就记着这个缺口，说「将来要补一个绝对下限」，这就是。

数值是照着上面那张表定的，落在悬崖下面一点：正常的一集里它几乎不起作用（第 1 集只多砍
5 条、第 2 集 2 条），只有素材真的坏掉时才会咬住。**它没有在真的坏素材上验过**，因为手上
还没有那样的一集。
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


def _above_floor(stoi: float, pesq: float, sisdr: float) -> bool:
    """三项绝对下限都过了没有。见 `MIN_STOI` 那段说明。

    这里只写一遍，是因为「留哪些」这件事有两个入口（`keep_best` 吃打过分的对象，
    `select_rows` 吃 `quality.json` 里的原始行），两边必须说一样的话。
    """
    return stoi >= MIN_STOI and pesq >= MIN_PESQ and sisdr >= MIN_SISDR


def passes_floor(q: Quality) -> bool:
    """这条片段过没过绝对下限。"""
    return _above_floor(q.stoi, q.pesq, q.sisdr)


def select_rows(rows: list[dict[str, Any]], keep_ratio: float = KEEP_RATIO) -> list[dict[str, Any]]:
    """跟 `keep_best` 同一套规矩，但吃 `quality.json` 里读出来的原始行。

    给 `avs embed` 和 `avs label` 用。它们要的是「这一集最后留下哪些片段」，答案必须跟
    管线里筛出来的完全一致，所以不能各自再写一遍排序和门槛。
    """
    ordered = sorted(rows, key=lambda r: -float(r["score"]))
    cut = max(1, int(len(ordered) * keep_ratio)) if ordered else 0
    return [
        r
        for r in ordered[:cut]
        if _above_floor(float(r["stoi"]), float(r["pesq"]), float(r["sisdr"]))
    ]


def keep_best(
    scored: list[Quality], keep_ratio: float = KEEP_RATIO
) -> tuple[list[Quality], list[Quality]]:
    """留下音质最好的一部分，其余淘汰。返回 (留下的, 淘汰的)。

    两道关，都要过：先按分数排名留下前 `keep_ratio`，再逐条过一遍绝对下限。前者管「这一集
    里哪些相对更好」，后者管「好到能用没有」—— 只有前者的话，一集整体都差时它照样留下 70%。

    淘汰的也带回去，不要直接丢：万一比例定错了能捞回来，这是 HOW_IT_WORKS 4.7 的规矩。
    """
    ordered = sorted(scored, key=lambda q: -q.score)
    cut = max(1, int(len(ordered) * keep_ratio)) if ordered else 0
    kept = [q for q in ordered[:cut] if passes_floor(q)]
    rejected = [q for q in ordered[:cut] if not passes_floor(q)] + ordered[cut:]
    return kept, rejected


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
