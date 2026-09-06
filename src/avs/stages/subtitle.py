"""读取对白字幕并估计它相对音轨的偏移；片段直接采用字幕边界。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_LINE = 20.0
DIALOGUE_STYLE = "Default"
SEARCH_SECONDS = 30.0
STEP = 0.01
MIN_OVERLAP_RATIO = 0.6


def load_dialogue(path: Path) -> list[dict[str, Any]]:
    """读一个 ASS 字幕文件，只挑出对白行，按时间排好，带上台词正文。

    挑的规矩见 `DIALOGUE_STYLE` 和 `MAX_LINE`。另外还会扔掉两种东西：正文是空的
    （那种整行都是排版指令），以及字幕组用来分段的 `====` 分隔行。
    """
    import pysubs2

    subs = pysubs2.load(str(path))
    lines = [
        {
            "start": event.start / 1000.0,
            "end": event.end / 1000.0,
            "text": event.plaintext.strip(),
        }
        for event in subs
        if event.style == DIALOGUE_STYLE
        and event.end > event.start
        and (event.end - event.start) / 1000.0 <= MAX_LINE
        and event.plaintext.strip()
        and "====" not in event.plaintext
    ]
    return sorted(lines, key=lambda line: (line["start"], line["end"]))


def load_lines(path: Path) -> list[tuple[float, float]]:
    """对白行的时间，按时间排好。切段只关心时间，正文见 `load_dialogue`。"""
    return [(line["start"], line["end"]) for line in load_dialogue(path)]


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
