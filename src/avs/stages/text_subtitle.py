"""导出时给台词换一份文字：片段照旧按切片段的那份字幕切，文字从另配的字幕里取。

用途是中文字幕切片段、日文字幕给文字，训练日语模型要的是日语原文。两份字幕的分行和
时间都不一样，所以先量出另配的字幕相对音轨差多少秒，再一条片段一条片段地找它的台词，
找不全的就不导出，记下原因。实测见 docs/EXPERIMENTS.md 的「日文台词」。

日文字幕常见的写法，这里都照顾到了：
- 一个字幕条目里的几行常常是两个人各说一句，所以拆成行，条目的时间按字数分给各行。
- 行首的（名字）是画外音标出说话人，拿来认出混进来的别人的话，正文里去掉。
- 其余括号里的是声音说明，比如（歓声），去掉。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MIN_AGREEMENT = 0.6
"""对上之后两份字幕显示时间的重合度（交集除以并集）至少这么多，否则多半不是这一集的字幕。

第 1 至 3 集上，四个来源的日文字幕对中文字幕在 0.67 到 0.78 之间，拿错成下一集的只有 0.50 左右。"""

MIN_MATCHED = 0.95
"""对上之后至少这么多片段要碰得到台词。第 1 至 3 集是 99% 以上，拿错成下一集也有 83% 到 88%：
台词密的地方随便错开都能碰到几行，所以这一道只能拦明显的错，主要靠重合度。"""

TOUCH = 0.1
"""一行和片段重叠超过这么多秒才算碰到。"""

INSIDE = 0.7
"""碰到的每一行至少这么多落在片段里。"""

SPARE = 0.8
"""字幕比说话多显示一会儿是常事：一行两头各伸出片段不到这么多秒，也算整行在里面。"""

COVER = 0.5
"""碰到的行合起来至少盖住片段这么多，否则片段里有一段话没有文字。"""

MIXED = 0.2
"""标了别人名字的行和片段重叠超过这么多秒，就是片段里混着别人的话。"""

OWN_TAG_SHARE = 0.5
"""一个角色的片段碰到的带名字的行里，同一个名字要占到这么多，才认它是这个角色在字幕里的名字。"""

_TAG = re.compile(r"^[（(]([^）)]*)[）)]")
_NOTE = re.compile(r"[（(][^）)]*[）)]")


@dataclass(frozen=True)
class TextLine:
    start: float
    end: float
    text: str
    speaker: str
    """行首（名字）里的名字，没有就是空的。"""


def load_text_lines(path: Path) -> list[TextLine]:
    """读 ASS 或 SRT，拆成行，去掉说话人标记和声音说明，按时间排好。时间是字幕自己的。"""
    import pysubs2

    lines: list[TextLine] = []
    for event in pysubs2.load(str(path)):
        if event.end <= event.start:
            continue
        parts = []
        for raw in event.plaintext.split("\n"):
            text, speaker = raw.strip(), ""
            tag = _TAG.match(text)
            if tag:
                speaker, text = tag.group(1).strip(), text[tag.end() :]
            text = _NOTE.sub("", text).strip()
            if text:
                parts.append((text, speaker))
        total = sum(len(text) for text, _ in parts)
        at, span = event.start / 1000.0, (event.end - event.start) / 1000.0
        for text, speaker in parts:
            length = span * len(text) / total
            lines.append(TextLine(at, at + length, text, speaker))
            at += length
    return sorted(lines, key=lambda line: (line.start, line.end))


def shifted(lines: list[TextLine], offset: float) -> list[TextLine]:
    return [TextLine(x.start + offset, x.end + offset, x.text, x.speaker) for x in lines]


def measure_offset(
    lines: list[TextLine], cut_lines: list[tuple[float, float]]
) -> tuple[float, float]:
    """另配的字幕要加多少秒才对上音轨。返回（偏移, 重合度）。

    `cut_lines` 是切片段那份字幕的行，已经换算到音轨时间。两份字幕说的是同一串台词，
    显示时间大体一样，所以拿它们互相比，和 `find_offset` 拿字幕比语音检测是同一个量法。
    """
    from avs.stages.subtitle import find_offset

    if not lines or not cut_lines:
        return 0.0, 0.0
    duration = max(max(x.end for x in lines), max(end for _, end in cut_lines))
    return find_offset([(x.start, x.end) for x in lines], cut_lines, duration)


def _shared(line: TextLine, start: float, end: float) -> float:
    return min(line.end, end) - max(line.start, start)


def touching(lines: list[TextLine], start: float, end: float) -> list[TextLine]:
    return [x for x in lines if _shared(x, start, end) > TOUCH]


def own_tag(hits: Iterable[TextLine]) -> str | None:
    """一个角色在字幕里的名字。`hits` 是这个角色所有片段碰到的行；其中带名字的行里最常见的
    那个名字，占不到 `OWN_TAG_SHARE` 就是 None。"""
    tags = Counter(x.speaker for x in hits)
    tags.pop("", None)
    if not tags:
        return None
    name, count = tags.most_common(1)[0]
    return name if count >= OWN_TAG_SHARE * sum(tags.values()) else None


def match(
    lines: list[TextLine], start: float, end: float, tag: str | None = None
) -> tuple[str, str | None]:
    """片段的台词文字和不收它的原因。原因是 None 才算对上了。

    `tag` 是这个角色在字幕里的名字（见 `own_tag`）。知道时，标了别的名字的行就是别人的话；
    不知道时，只有碰到的行标了两个以上不同名字才算混进了别人。
    """
    hits = touching(lines, start, end)
    named = {x.speaker for x in hits if x.speaker}
    others = [x for x in hits if x.speaker and x.speaker != tag] if tag else []
    if any(_shared(x, start, end) > MIXED for x in others) or (not tag and len(named) > 1):
        return "", "台词里有别人的话"
    hits = [x for x in hits if x not in others]
    texts: list[str] = []
    for x in hits:
        if x.text not in texts:  # 同一句常被重复显示
            texts.append(x.text)
    text = " ".join(texts)
    if not hits:
        return "", "没有对上的台词"
    for x in hits:
        inside = _shared(x, start, end) / (x.end - x.start)
        if inside < INSIDE and max(start - x.start, x.end - end) > SPARE:
            return text, "有一行台词只对上一部分"
    covered = sum(_shared(x, start, end) for x in hits) / (end - start)
    if covered < COVER:
        return text, "台词只盖住片段一小部分"
    return text, None
