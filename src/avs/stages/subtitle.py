"""按字幕行把候选片段切开，让一条片段里只剩一个人说的一句话。

**它解决的是这个项目最卡人的那个问题。** 音质筛选留下的片段里仍有 26% 不止一个人在说话，
而 pyannote 看不见这些声音（`STATUS.md` 里有实测）。字幕能看见：一行字幕基本就是一个人的
一句台词，所以**片段跨了几行字幕，就说明它里面有几句话**。第 1 集实测，9 条人工确认「不止
一个人」的片段**没有一条只盖住 1 行字幕**，也就是说全都能在字幕边界上切开。

**为什么是切，不是扔。** 这一点决定了它比别的办法值钱得多：

| | 条数 | 合计时长 |
| --- | --- | --- |
| 不做这一步 | 180 | 605 秒 |
| **按字幕切开** | **241** | **513 秒（留下 85%）** |
| 换成「按声纹一致性砍掉最脏的一半」 | 90 | 约 300 秒 |

**它管不了什么。** 一群人在欢呼、两个人同时出声，切在哪儿都还是脏的 —— 那一族得靠音质筛选
（下一步）去挡。所以这一步不是万能的，它只负责「一条里有好几句话」这一族。

**代价是没有台词的声音会整条消失。** 惊呼、笑声、喘息这些字幕里没有，切完什么都不剩。第 1 集
180 条里有 15 条这样。这正是决策 7 当初拒绝用字幕切段的理由，代价是真的，只是比想象中小。
所以这些片段是**退回**而不是丢弃，跟 `HOW_IT_WORKS.md` 4.7 的规矩一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_OVERLAP = 0.2
"""字幕行跟片段重合不到这么久，就当它们没关系，单位秒。

防的是「一行字幕的尾巴擦到了下一个片段的头」这种情况，那点重合不代表这句话在这条片段里。
"""

MIN_PIECE = 1.0
"""切出来短于这个长度的碎片直接不要，单位秒。

跟 `embeddings/extract.py` 的门槛一致：短于 1 秒的片段指纹不可靠，留着也没法参与分组。
第 1 集实测，用 1.0 秒这个门槛切出来 241 条共 513 秒，没有一条短于 1 秒。
"""

MAX_LINE = 20.0
"""长于这么久的字幕行不当台词看，单位秒。那种基本是 OP、ED 的整段歌词或者说明性字幕。"""

DIALOGUE_STYLE = "Default"
"""ASS 字幕里对白用的样式名。

别的样式是招牌翻译（`sign_*`）、staff 表、OP/ED 歌词（`INJP`、`EDCN`）这些，
它们不对应任何人说的话，拿来切段只会切错。
"""

SEARCH_SECONDS = 30.0
"""对齐时在正负这么大的范围里找偏移，单位秒。"""

STEP = 0.01
"""对齐时每次挪多少，单位秒。10 毫秒足够，字幕本身的精度也就这个量级。"""

MIN_OVERLAP_RATIO = 0.6
"""对齐之后两条时间线的重合度低于这个数，就认为字幕根本对不上这一集。

**这条检查非常重要**：拿错集数的字幕文件不会报错，只会安静地把所有片段切错位置，
而切错的片段听着仍然像话，很难发现。第 1 集对上时是 0.744。
"""


@dataclass(frozen=True)
class Piece:
    """切出来的一小段。`speaker` 沿用它所属的那条片段的标签，字幕不改变「这是谁」的判断。"""

    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def load_lines(path: Path) -> list[tuple[float, float]]:
    """读一个 ASS 字幕文件，只挑出对白行的时间，按时间排好。

    挑的规矩见 `DIALOGUE_STYLE` 和 `MAX_LINE`。另外还会扔掉两种东西：正文是空的
    （那种整行都是排版指令），以及字幕组用来分段的 `====` 分隔行。
    """
    import pysubs2

    subs = pysubs2.load(str(path))
    lines = [
        (event.start / 1000.0, event.end / 1000.0)
        for event in subs
        if event.style == DIALOGUE_STYLE
        and event.end > event.start
        and (event.end - event.start) / 1000.0 <= MAX_LINE
        and event.plaintext.strip()
        and "====" not in event.plaintext
    ]
    return sorted(lines)


def _mask(spans: list[tuple[float, float]], length: int) -> Any:
    """把一串时间区间画成一条 10 毫秒一格的时间线，有东西的地方是 1。"""
    import numpy as np

    grid = np.zeros(length, dtype=np.float64)
    for start, end in spans:
        low = max(0, int(start / STEP))
        high = min(length, int(end / STEP))
        if high > low:
            grid[low:high] = 1.0
    return grid


def find_offset(
    lines: list[tuple[float, float]], speech: list[tuple[float, float]], duration: float
) -> tuple[float, float]:
    """字幕跟这一集的音轨差多少秒。返回（偏移, 对上之后的重合度）。

    **为什么必须量而不能写死。** 字幕是给视频配的，而我们手上的音轨是另外抽出来的，两边
    差多少取决于片源。第 1 集实测差 0.94 秒；第 5 集起换了片源版本，偏移几乎肯定不一样。

    量法：把「字幕在显示」和「模型认为有人说话」两条时间线错开着比，看错开多少时重合最多。
    重合度是两条线的交集除以并集，1.0 表示完全重合。

    重合度太低（低于 `MIN_OVERLAP_RATIO`）说明字幕根本不是这一集的，调用方要当错误处理，
    别硬着头皮往下切。
    """
    import numpy as np

    length = int((duration + SEARCH_SECONDS) / STEP)
    subtitle = _mask(lines, length)
    spoken = _mask(speech, length)

    best_offset, best_score = 0.0, -1.0
    for shift in np.arange(-SEARCH_SECONDS, SEARCH_SECONDS, STEP):
        moved = np.roll(subtitle, int(shift / STEP))
        union = float(((moved + spoken) > 0).sum())
        score = float((moved * spoken).sum()) / union if union else 0.0
        if score > best_score:
            best_offset, best_score = float(shift), score
    return round(best_offset, 3), round(best_score, 4)


def split_segments(
    segments: list[Any],
    lines: list[tuple[float, float]],
    offset: float = 0.0,
    min_piece: float = MIN_PIECE,
) -> tuple[list[Piece], list[Any]]:
    """按字幕行把片段切开。返回（切出来的小段, 一点都没剩下的原片段）。

    一条片段跟哪几行字幕重合，就切成哪几段，每段取「片段跟这行字幕的公共部分」。所以
    字幕行之间的空隙会被丢掉，那正是我们要的：空隙多半是换人的地方。

    **退回的那些不要直接扔**，它们是完全落在字幕之外的片段，多半是惊呼、笑声、喘息这类
    没有台词但对音色有用的声音，留给调用方决定怎么处置。
    """
    kept: list[Piece] = []
    dropped: list[Any] = []

    for segment in segments:
        start, end = float(segment["start"]), float(segment["end"])
        pieces = []
        for line_start, line_end in lines:
            low = max(start, line_start + offset)
            high = min(end, line_end + offset)
            if high - low >= MIN_OVERLAP and high - low >= min_piece:
                pieces.append(Piece(speaker=str(segment["speaker"]), start=low, end=high))
        if pieces:
            kept.extend(pieces)
        else:
            dropped.append(segment)

    kept.sort(key=lambda p: p.start)
    return kept, dropped


def summarize(
    kept: list[Piece], dropped: list[Any], before: list[Any], offset: float, overlap: float
) -> dict[str, Any]:
    """切完之后剩多少料，跟切之前比。"""
    was = sum(float(s["end"]) - float(s["start"]) for s in before)
    now = sum(p.duration for p in kept)
    return {
        "offset_sec": offset,
        "overlap": overlap,
        "before": len(before),
        "before_sec": round(was, 1),
        "after": len(kept),
        "after_sec": round(now, 1),
        "kept_ratio": round(now / was, 4) if was else 0.0,
        "dropped": len(dropped),
        "dropped_sec": round(sum(float(s["end"]) - float(s["start"]) for s in dropped), 1),
    }
