"""Read a dialogue subtitle file and estimate its offset from the audio track. Clips take the
subtitle boundaries directly.

The file format is fixed, so pysubs2 reads the times and text of every line. Two things vary from
one subtitle group to the next, and both are handled here without asking the person to fix the
file: the text encoding, and which style (the named look an ASS file gives each line, such as
"Default" or "OP") holds the dialogue.
"""

from __future__ import annotations

import codecs
import re
from collections import Counter
from pathlib import Path
from typing import Any

from avoc.language import say

MAX_LINE = 20.0
SEARCH_SECONDS = 30.0
STEP = 0.01
MIN_OVERLAP_RATIO = 0.6

OTHER_ENCODINGS = ["gb18030", "big5", "cp932", "euc_jp", "euc_kr", "cp1252"]
"""Encodings tried for a file that is not UTF-8. Older Chinese subtitles are often GBK (GB18030
covers it) or Big5, older Japanese ones Shift-JIS (cp932 covers it), and older Western ones
Windows-1252. charset-normalizer picks the one whose text reads most like real language. On our
Chinese and Japanese subtitles saved in each of these, it found the right one every time."""

HALF_WIDTH_KANA = re.compile("[｡-ﾟ]")
"""Half-width katakana, which subtitles almost never use. Chinese text read as Shift-JIS turns into
it, and with only a few Chinese lines charset-normalizer can rate that reading as good as the
right one."""

BYTE_ORDER_MARKS = [
    (codecs.BOM_UTF32_LE, "utf-32"),  # Checked before UTF-16, whose mark it starts with.
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]

PARTS = 10
SPREAD = 0.5
"""A dialogue style has lines in at least this share of the episode. The time from the first line to
the last is cut into `PARTS` equal parts. Dialogue reaches nearly all of them. Opening and ending
songs sit in one or two."""

SIDE_STYLE = 0.25
"""A second style that is also spread through the episode, with at least this share of the main
style's line count, is dialogue too. This is the usual layout of bilingual subtitles that keep each
language in its own style. Signs and on-screen text are far fewer: in our Chinese subtitles, 40
sign lines against 402 dialogue lines."""


def decode_subtitles(data: bytes) -> tuple[str, str]:
    """The text of a subtitle file, and the name of the encoding it was read with."""
    for mark, encoding in BYTE_ORDER_MARKS:
        if data.startswith(mark):
            return data.decode(encoding), encoding
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes

    found = list(from_bytes(data, cp_isolation=OTHER_ENCODINGS))  # Best first.
    plausible = [m for m in found if not HALF_WIDTH_KANA.search(str(m))]
    if not found:
        raise UnicodeError("unknown text encoding")
    best = (plausible or found)[0]
    return str(best), best.encoding


def open_subtitles(path: Path) -> tuple[Any, str]:
    """Open a subtitle file with pysubs2, and say which encoding it was read with. pysubs2 tells
    the format from the content, not the file extension: ASS, SSA, SRT, WebVTT and a few more.
    Any problem becomes a ValueError with a plain reason, instead of a library error deep in a
    traceback."""
    import pysubs2

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(
            say(
                f"打不开这个字幕文件：{path}（{exc}）",
                f"cannot open this subtitle file: {path} ({exc})",
            )
        ) from exc
    try:
        text, encoding = decode_subtitles(data)
    except UnicodeError as exc:
        raise ValueError(
            say(
                f"认不出这个字幕文件的文字编码：{path}。用记事本之类的工具把它另存为 UTF-8 再试",
                f"cannot tell the text encoding of this subtitle file: {path}. Save it as UTF-8 "
                "with a text editor, then try again",
            )
        ) from exc
    try:
        return pysubs2.SSAFile.from_string(text), encoding
    except pysubs2.Pysubs2Error as exc:
        raise ValueError(
            say(
                f"读不出这个字幕文件，它要是 ASS 或 SRT：{path}（{exc}）",
                f"cannot read this subtitle file; it must be ASS or SRT: {path} ({exc})",
            )
        ) from exc


def read_subtitles(path: Path) -> Any:
    return open_subtitles(path)[0]


def usable(event: Any) -> bool:
    """Whether a subtitle line can be a dialogue line, whatever its style. Dropped: comment lines,
    vector drawings, lines with no text (only layout commands), lines longer than `MAX_LINE`, and
    the `====` separator lines that fansub groups (subtitle teams) use to split sections."""
    return (
        event.is_text  # Neither a comment nor a drawing.
        and 0 < event.end - event.start <= MAX_LINE * 1000
        and bool(event.plaintext.strip())
        and "====" not in event.plaintext
    )


def pick_styles(subs: Any) -> list[str]:
    """The styles that hold the dialogue, most lines first. Empty only if no line is usable.

    The main style is the one with the most lines among the styles spread through the episode (see
    `SPREAD`). Also picked: styles whose name starts with the main style's name, such as
    "Default - Top" for a second speaker at the top of the screen, and other spread styles with
    enough lines (see `SIDE_STYLE`). An SRT file has no styles; pysubs2 puts every line in
    "Default", so all of them are picked.
    """
    events = [e for e in subs if usable(e)]
    if not events:
        return []
    counts = Counter(e.style for e in events)
    first = min(e.start for e in events)
    width = max(1, max(e.end for e in events) - first) / PARTS
    parts: dict[str, set[int]] = {}
    for e in events:
        parts.setdefault(e.style, set()).add(min(PARTS - 1, int((e.start - first) / width)))
    spread = [s for s in counts if len(parts[s]) >= SPREAD * PARTS]
    main = max(spread or counts, key=lambda s: counts[s])
    return [
        s
        for s, n in counts.most_common()
        if s == main
        or s.casefold().startswith(main.casefold())
        or (s in spread and n >= SIDE_STYLE * counts[main])
    ]


def describe_styles(path: Path) -> dict[str, Any]:
    """What a person needs to check or change the styles picked: each style's line count, time
    range and a few sample lines, and the styles `pick_styles` chose."""
    subs, encoding = open_subtitles(path)
    by_style: dict[str, list[Any]] = {}
    for event in sorted((e for e in subs if usable(e)), key=lambda e: e.start):
        by_style.setdefault(event.style, []).append(event)
    styles = []
    for name, events in sorted(by_style.items(), key=lambda item: -len(item[1])):
        picks = sorted({0, len(events) // 2, len(events) - 1})
        styles.append(
            {
                "name": name,
                "lines": len(events),
                "first": events[0].start / 1000.0,
                "last": max(e.end for e in events) / 1000.0,
                "samples": [" ".join(events[i].plaintext.split()) for i in picks],
            }
        )
    return {
        "format": subs.format,
        "encoding": encoding,
        "styles": styles,
        "picked": pick_styles(subs),
    }


def styles_note(path: Path, styles: list[str] | None = None) -> str:
    """One line for the person: which styles the dialogue is taken from, and which are left out."""
    found = describe_styles(path)
    chosen = found["picked"] if styles is None else styles
    named = [f"{s['name']} ({s['lines']})" for s in found["styles"] if s["name"] in chosen]
    rest = [f"{s['name']} ({s['lines']})" for s in found["styles"] if s["name"] not in chosen]
    if not rest:
        return say(f"台词取自样式 {', '.join(named)}", f"Dialogue taken from {', '.join(named)}")
    return say(
        f"台词取自样式 {', '.join(named)}；没用：{', '.join(rest)}。要改就用 --styles",
        f"Dialogue taken from {', '.join(named)}; left out: {', '.join(rest)}. "
        "To change this, use --styles",
    )


def load_dialogue(path: Path, styles: list[str] | None = None) -> list[dict[str, Any]]:
    """Read one subtitle file, keep only the dialogue lines, sort them by time, and include the
    line text.

    `styles` names the styles that hold the dialogue. If it is None, they are picked by
    `pick_styles`. Lines are dropped as described in `usable`.
    """
    subs = read_subtitles(path)
    if styles is None:
        styles = pick_styles(subs)
    else:
        check_styles(subs, styles)
    lines = [
        {
            "start": event.start / 1000.0,
            "end": event.end / 1000.0,
            "text": event.plaintext.strip(),
        }
        for event in subs
        if event.style in styles and usable(event)
    ]
    return sorted(lines, key=lambda line: (line["start"], line["end"]))


def check_styles(subs: Any, styles: list[str]) -> None:
    """Refuse a list of styles that is empty or names a style with no usable lines in the file."""
    present = Counter(e.style for e in subs if usable(e))
    if not styles:
        raise ValueError(say("至少要选一个样式", "choose at least one style"))
    missing = [s for s in styles if s not in present]
    if missing:
        have = ", ".join(f"{s} ({n})" for s, n in present.most_common())
        raise ValueError(
            say(
                f"字幕里没有样式 {', '.join(missing)}。有的样式：{have}",
                f"the subtitles have no style {', '.join(missing)}. Styles there: {have}",
            )
        )


def load_lines(path: Path, styles: list[str] | None = None) -> list[tuple[float, float]]:
    """The times of the dialogue lines, sorted by time. Clipping only needs the times. For the text,
    see `load_dialogue`."""
    return [(line["start"], line["end"]) for line in load_dialogue(path, styles)]


def _mask(spans: list[tuple[float, float]], length: int) -> Any:
    """Draw a list of time spans as a timeline with one cell per 10 milliseconds. Cells that contain
    something are 1."""
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
    """How many seconds the subtitles differ from this episode's audio track. Returns (offset,
    overlap score).

    **Why it must be measured and not written in as a fixed number.** The subtitles were made for
    the video, while the audio track we have was extracted separately, so the difference depends on
    the source. In episode 1 it measured 0.94 seconds. From episode 5 on, the source version
    changed, so the offset is almost certainly different.

    How it is measured: slide the "subtitle is showing" timeline against the "model thinks someone
    is speaking" timeline, and find the shift at which they overlap the most. The overlap score is
    the intersection of the two lines divided by their union, so 1.0 means a perfect match.

    If the overlap score is too low (below `MIN_OVERLAP_RATIO`), the subtitles do not belong to this
    episode. The caller must treat that as an error and not push on with cutting.
    """
    import numpy as np

    length = int((duration + SEARCH_SECONDS) / STEP)
    subtitle = _mask(lines, length)
    spoken = _mask(speech, length)

    # Shift by whole cells, so the offset reported is exactly the shift used for scoring. A rounding
    # difference of one cell cannot creep in.
    best_offset, best_score = 0.0, -1.0
    reach = round(SEARCH_SECONDS / STEP)
    for steps in range(-reach, reach):
        moved = np.roll(subtitle, steps)
        union = float(((moved + spoken) > 0).sum())
        score = float((moved * spoken).sum()) / union if union else 0.0
        if score > best_score:
            best_offset, best_score = steps * STEP, score
    return round(best_offset, 3), round(best_score, 4)
