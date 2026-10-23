"""When exporting, swap the text of each dialogue line. Clips are still cut by the subtitles they
were cut with, but the text is taken from separately supplied subtitles.

The use case: Chinese subtitles are used to cut the clips, and Japanese subtitles supply the text,
because training a Japanese model needs the original Japanese. The two subtitle files have
different line breaks and times. So first measure how many seconds the separate subtitles must be
shifted to line up with the audio. Then find the dialogue for each clip, one clip at a time. A clip
whose dialogue cannot be found in full is not exported, and the reason is recorded. Measurements
are in docs/EXPERIMENTS.md, section "Japanese dialogue".

Common patterns in Japanese subtitles are handled here:
- Several lines in one subtitle entry are often two people each saying one sentence. So the entry
  is split into lines, and its time is shared among the lines by character count.
- A speaker tag such as (Name) at the start of a line names the speaker. It is used to spot other
  people's lines that got mixed in, and it is removed from the text.
- Other brackets hold sound notes, such as （歓声）, and they are removed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from avs.language import say

MIN_AGREEMENT = 0.6
"""After matching, the two subtitle files must agree on display times (overlap divided by union) by
at least this much. Otherwise they probably are not the subtitles for this episode.

In episodes 1 to 3, the four sources of Japanese subtitles scored between 0.67 and 0.78 against the
Chinese subtitles. A wrong match to the next episode scored only about 0.50."""

MIN_MATCHED = 0.95
"""After matching, at least this share of clips must touch some dialogue. In episodes 1 to 3 it was
99% or more. A wrong match to the next episode still got 83% to 88%, because where dialogue is
dense, even a shifted match touches a few lines. So this check only catches obvious errors. The
overlap score does most of the work."""

TOUCH = 0.1
"""A line counts as touching a clip only if they overlap by more than this many seconds."""

INSIDE = 0.7
"""At least this share of each touching line must fall inside the clip."""

SPARE = 0.8
"""Subtitles often stay on screen a little longer than the speech. If a line sticks out past the
clip at either end by less than this many seconds, the whole line still counts as inside."""

COVER = 0.5
"""The touching lines together must cover at least this share of the clip. Otherwise part of the
clip has no text."""

MIXED = 0.2
"""A line tagged with someone else's name that overlaps the clip by more than this many seconds
means someone else's speech is mixed into the clip."""

OWN_TAG_SHARE = 0.5
"""For a character's clips, one name must make up at least this share of the named lines they
touch. Only then is that name accepted as the character's name in the subtitles."""

_TAG = re.compile(r"^[（(]([^）)]*)[）)]")
_NOTE = re.compile(r"[（(][^）)]*[）)]")


@dataclass(frozen=True)
class TextLine:
    start: float
    end: float
    text: str
    speaker: str
    """The name in the speaker tag at the start of the line. Empty if there is none."""


def load_text_lines(path: Path) -> list[TextLine]:
    """Read an ASS or SRT file, split it into lines, remove speaker tags and sound notes, and sort
    by time. The times are the subtitle file's own."""
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
    """How many seconds the separate subtitles must be shifted to line up with the audio. Returns
    (offset, overlap score).

    `cut_lines` are the lines of the subtitles used for cutting, already converted to audio-track
    time. Both subtitle files carry the same dialogue, with roughly the same display times. So they
    are compared with each other, using the same method that `find_offset` uses to compare
    subtitles with speech detection.
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
    """The name this character has in the subtitles. `hits` are the lines touched by all of this
    character's clips. If the most common name among the named lines makes up less than
    `OWN_TAG_SHARE`, the result is None."""
    tags = Counter(x.speaker for x in hits)
    tags.pop("", None)
    if not tags:
        return None
    name, count = tags.most_common(1)[0]
    return name if count >= OWN_TAG_SHARE * sum(tags.values()) else None


def match(
    lines: list[TextLine], start: float, end: float, tag: str | None = None
) -> tuple[str, str | None]:
    """The clip's dialogue text, and the reason it is not accepted. A reason of None means it
    matched.

    `tag` is this character's name in the subtitles (see `own_tag`). When it is known, lines tagged
    with another name are someone else's speech. When it is not known, lines count as someone
    else's only if the touched lines carry two or more different names.
    """
    hits = touching(lines, start, end)
    named = {x.speaker for x in hits if x.speaker}
    others = [x for x in hits if x.speaker and x.speaker != tag] if tag else []
    if any(_shared(x, start, end) > MIXED for x in others) or (not tag and len(named) > 1):
        return "", say("台词里有别人的话", "someone else's line is mixed in")
    hits = [x for x in hits if x not in others]
    texts: list[str] = []
    for x in hits:
        if x.text not in texts:  # The same line is often shown twice.
            texts.append(x.text)
    text = " ".join(texts)
    if not hits:
        return "", say("没有对上的台词", "no matching line")
    for x in hits:
        inside = _shared(x, start, end) / (x.end - x.start)
        if inside < INSIDE and max(start - x.start, x.end - end) > SPARE:
            return text, say("有一行台词只对上一部分", "a line only partly matches")
    covered = sum(_shared(x, start, end) for x in hits) / (end - start)
    if covered < COVER:
        return text, say("台词只盖住片段一小部分", "the lines cover only a small part of the clip")
    return text, None
