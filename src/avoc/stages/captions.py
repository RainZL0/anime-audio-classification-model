"""Turn the text of one subtitle entry into the words people speak, and the speaker if the subtitles
name one.

Subtitles made for viewers who cannot hear add things nobody says: speaker names, sound notes such
as （歓声） or [laughs], music notes around song lyrics, and marks that TV captions use, such as ➡
for "the sentence goes on" or a microphone sign. Each subtitle maker has its own habits. This file
is the only place that knows them, so a new habit is handled by changing this file and nothing
else.
`leftovers` reports lines that still look marked, so a habit the rules miss shows up at once
instead of in the training text. See docs/SUBTITLES.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from avoc.language import say

VOICE_MARKS = re.compile(r"\(\(|\)\)|（（|））|[《》≪≫＜＞<>]")
"""Marks around words that are spoken, so only the marks go: (( )) and 《 》 in TV captions, ＜ ＞
for a voice over the phone or a narrator."""

READING = re.compile(r"(?<=[一-鿿々])[（(][ぁ-ゖー]+[）)]")
"""How a word in kanji is read, in brackets right after it: 中山(なかやま). It can sit inside a
speaker name, as in （細江純子(じゅんこ)）, so it goes first."""

OPENING = "（(［[【{｛"
CLOSING = "）)］]】}｝"

TAG = re.compile(r"^[（(]([^（()）]{1,30})[）)]\s*")
"""A speaker name in brackets at the start of a line: （テイオー）ねえ. The same brackets later in
a line hold a sound note."""

COLON_TAG = re.compile(r"^([^\s：:（()）「『]{1,12})[：:]\s*")
"""A speaker name before a colon: リオナタール：何か, ２人：負けない, JOHN: Wait. A name in Latin
letters must be in capitals, so that "Note: ..." stays dialogue, and a name of only digits is a
time such as 10:30."""

NOTE = re.compile(
    r"[（(][^（()）]*[）)]|[［\[][^［\[\]］]*[］\]]|【[^【】]*】|[{｛][^{｛}｝]*[}｝]"
)
"""A sound note or a sign in brackets: （歓声）, [laughs], [ﾏｲｸ], 【回想】. Applied until nothing is
left, so nested marks such as [[]] go too."""

MUSIC = "♪♫♬♩"
"""A line that starts with a music note is a song lyric. A note at the end of spoken words, as in
やった～♪, is only decoration."""

CLEANUP: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"^mic(?=[^\x00-\x7f])"),
        "",
        "A microphone sign some TV caption files spell 'mic'",
    ),
    (re.compile(r"^[-‐－]\s*"), "", "A dash that opens one speaker's line when two people speak"),
]
"""Other habits seen in real subtitles: (pattern, replacement, what it is). Applied to each line in
order, before the speaker name is looked for."""

LEFTOVER = re.compile(rf"[{re.escape(OPENING + CLOSING)}《》＜＞<>〈〉]|^[^\s：:]{{1,12}}[：:]")
"""Marks that should not be left in spoken words: any bracket except the quotes 「」『』, or a name
before a colon."""


def _symbol(char: str) -> bool:
    """Arrows, emoji, music notes, stars and such: never spoken."""
    return unicodedata.category(char) == "So"


def _unclosed(line: str) -> bool:
    depth = 0
    for char in line:
        if char in "（(":
            depth += 1
        elif char in "）)" and depth:
            depth -= 1
    return depth > 0


def _join(lines: list[str]) -> list[str]:
    """Join a line whose bracket closes on a later line: a long name or note is often wrapped, as
    in （サトノダイヤモンド・ then キタサンブラック）おお…"""
    joined: list[str] = []
    for line in lines:
        if joined and _unclosed(joined[-1]):
            glue = " " if joined[-1][-1:].isascii() and line[:1].isascii() else ""
            joined[-1] += glue + line
        else:
            joined.append(line)
    return joined


def spoken_lines(entry: str) -> list[tuple[str, str]]:
    """(words, speaker) for each line of one subtitle entry. The speaker is empty if no name is
    given. Lines with no spoken words, such as a lone sound note or a song lyric, are left out.

    A name alone on its line names the speaker of the next line, as in （女性） then あっ. A sound
    note alone on its line, such as （歓声）, looks the same and is taken as a name too. That only
    makes the check for someone else's speech stricter: fewer clips are exported, but no wrong text
    is."""
    found: list[tuple[str, str]] = []
    waiting = ""
    for line in _join([VOICE_MARKS.sub("", raw).strip() for raw in entry.split("\n")]):
        if line[:1] in MUSIC:
            continue
        line = READING.sub("", "".join(c for c in line if not _symbol(c))).strip()
        for pattern, replacement, _ in CLEANUP:
            line = pattern.sub(replacement, line)
        speaker, waiting = waiting, ""
        tag = TAG.match(line) or COLON_TAG.match(line)
        name = tag.group(1).strip() if tag else ""
        if tag and (
            tag.re is TAG or (not name.isdigit() and (not name.isascii() or name.isupper()))
        ):
            speaker, line = name, line[tag.end() :]
            if not line.strip():
                waiting = name
                continue
        while (lighter := NOTE.sub("", line)) != line:
            line = lighter
        line = re.sub(r"[｡-ﾟ]+", lambda m: unicodedata.normalize("NFKC", m[0]), line)
        line = " ".join(line.split())  # Also turns full-width spaces into plain ones.
        if any(c.isalnum() for c in line):  # Not just a wave dash or … left from a lyric or sigh.
            found.append((line, speaker))
    return found


def spoken(text: str) -> str:
    """The words of one subtitle entry on one line, without names, notes and marks."""
    return " ".join(words for words, _ in spoken_lines(text))


def leftovers(texts: Iterable[str]) -> list[str]:
    """The lines that still contain marks after cleaning: a habit the rules above do not know."""
    return [text for text in texts if LEFTOVER.search(text)]


def marked(texts: Iterable[str]) -> dict[str, Any] | None:
    """How many cleaned lines still contain marks, with a few of them. None if there are none."""
    found = list(dict.fromkeys(leftovers(texts)))
    return {"lines": len(found), "examples": found[:3]} if found else None


def marked_note(found: dict[str, Any]) -> str:
    """The warning for `marked`, for the person."""
    examples = "、".join(f"「{x}」" for x in found["examples"])
    return say(
        f"有 {found['lines']} 行台词还带着认不出的记号，比如 {examples}。导出的文字会带着它们，"
        "怎么处理见 docs/SUBTITLES.md",
        f"{found['lines']} lines still contain marks the rules do not know, such as {examples}. "
        "Exported text will include them; see docs/SUBTITLES.md for what to do",
    )
