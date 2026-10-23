"""Give each clip its text in the language spoken. Clips are still cut by the subtitles they were
cut with, but the text comes from lines in the spoken language: from the cutting subtitles when
they are in it (bilingual ones included), otherwise from separately supplied text subtitles.

The usual case: Chinese subtitles are used to cut the clips, and Japanese subtitles supply the text,
because training a Japanese model needs the original Japanese. The two subtitle files have
different line breaks and times. So first measure how many seconds the separate subtitles must be
shifted to line up with the audio. Then find the dialogue for each clip, one clip at a time. A clip
whose dialogue cannot be found in full is not exported, and the reason is recorded.

Several lines in one subtitle entry are often two people each saying one sentence. So the entry is
split into lines, and its time is shared among the lines by character count. Speaker names, sound
notes and other marks are removed by the rules in captions.py. A speaker name, where the subtitles
give one, is used to spot other people's lines that got mixed in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avoc.language import say

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


@dataclass(frozen=True)
class TextLine:
    start: float
    end: float
    text: str
    speaker: str
    """The name in the speaker tag at the start of the line. Empty if there is none."""


def _entries(path: Path, styles: list[str] | None) -> list[tuple[Any, list[tuple[str, str]]]]:
    """Each subtitle entry with its lines of spoken words, as (entry, [(words, speaker)]). With
    `styles`, only the dialogue lines of those styles, as clips are cut from them; without, every
    entry with text."""
    from avoc.stages.captions import spoken_lines
    from avoc.stages.subtitle import read_subtitles, usable

    found = []
    for event in read_subtitles(path):
        if event.end <= event.start or not event.is_text:  # Comments and drawings have no lines.
            continue
        if styles is not None and not (event.style in styles and usable(event)):
            continue
        if parts := spoken_lines(event.plaintext):
            found.append((event, parts))
    return found


def _languages(entries: list[tuple[Any, list[tuple[str, str]]]]) -> list[list[str | None]]:
    from avoc.stages.text_language import line_languages

    return line_languages((e.style, [text for text, _ in parts]) for e, parts in entries)


def subtitle_languages(path: Path, styles: list[str] | None = None) -> dict[str, float]:
    """The languages of a subtitle file's lines, with their shares, most first. A bilingual file
    has two. See stages/text_language.py."""
    from avoc.stages.text_language import file_languages

    return file_languages(code for codes in _languages(_entries(path, styles)) for code in codes)


def load_text_lines(
    path: Path, styles: list[str] | None = None, spoken: str | None = None
) -> list[TextLine]:
    """Read an ASS or SRT file, split it into lines of spoken words, and sort by time. The times
    are the subtitle file's own.

    With `spoken`, only the lines in that language are kept, so the Chinese half of a bilingual
    file is dropped. An entry's time is shared, by character count, among the lines kept.
    `styles` works as in `_entries`."""
    entries = _entries(path, styles)
    languages = _languages(entries) if spoken else [[None] * len(p) for _, p in entries]
    lines: list[TextLine] = []
    for (event, parts), codes in zip(entries, languages, strict=True):
        kept = [part for part, code in zip(parts, codes, strict=True) if code == spoken]
        total = sum(len(text) for text, _ in kept)
        at, span = event.start / 1000.0, (event.end - event.start) / 1000.0
        for text, speaker in kept:
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
    from avoc.stages.subtitle import find_offset

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


def same_name(a: str, b: str) -> bool:
    """Whether two speaker names are the same person. Subtitles often give the full name once and
    a short one after: トウカイテイオー and テイオー. テイオーたち is other people too."""
    return a.endswith(b) or b.endswith(a)


def match(
    lines: list[TextLine], start: float, end: float, tag: str | None = None
) -> tuple[str, str | None]:
    """The clip's dialogue text, and the reason it is not accepted. A reason of None means it
    matched.

    `tag` is this character's name in the subtitles (see `own_tag`). When it is known, lines tagged
    with another name are someone else's speech. When it is not known, lines count as someone
    else's only if the touched lines carry two or more different names.
    """
    return match_hits(touching(lines, start, end), start, end, tag)


def match_hits(
    hits: Sequence[TextLine], start: float, end: float, tag: str | None = None
) -> tuple[str, str | None]:
    """`match`, given the lines that touch the clip (see `touching`)."""
    named = {x.speaker for x in hits if x.speaker}
    others = [x for x in hits if x.speaker and not same_name(x.speaker, tag)] if tag else []
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
