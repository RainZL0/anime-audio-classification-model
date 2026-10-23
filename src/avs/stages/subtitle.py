"""Read a dialogue subtitle file and estimate its offset from the audio track. Clips take the
subtitle boundaries directly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_LINE = 20.0
DIALOGUE_STYLE = "Default"
SEARCH_SECONDS = 30.0
STEP = 0.01
MIN_OVERLAP_RATIO = 0.6


def load_dialogue(path: Path) -> list[dict[str, Any]]:
    """Read one ASS subtitle file, keep only the dialogue lines, sort them by time, and include the
    line text.

    The selection rules are in `DIALOGUE_STYLE` and `MAX_LINE`. Two more kinds of line are dropped
    as well: lines whose text is empty (those lines are only layout commands), and the `====`
    separator lines that fansub groups (subtitle teams) use to split sections.
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
    """The times of the dialogue lines, sorted by time. Clipping only needs the times. For the text,
    see `load_dialogue`."""
    return [(line["start"], line["end"]) for line in load_dialogue(path)]


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
