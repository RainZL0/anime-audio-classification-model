"""Dialogue coverage check: find which subtitle lines have no clip at all, and cut them out to
listen to.

Clips come from the intersection of the subtitle time range and the speech detected, and they
have a 1-second minimum length. So there are far fewer clips than dialogue lines in the subtitles.
Whether the missing lines are too quiet to hear, missed by detection, or simply meant to be
dropped can only be judged by ear. This module puts them in front of you.

The offset of the subtitles relative to the audio is no longer recomputed with speech detection.
The existing clips were all cut from the subtitles, so the mode (the most common value) of the
boundary differences is the offset. This needs neither the raw detection results, nor a
different boundary rule from the one used when the clips were cut.
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

from avs.labeling import stamp
from avs.project import load_episode, write_json

SEARCH_SECONDS = 3.0
STEP = 0.01
EDGE = 0.06
"""Boundary error allowed when deciding whether a clip lies inside a subtitle line. Covers rounding
to whole milliseconds."""
FLOOR = 1.0
"""Minimum clip length used when the clips were cut. A subtitle line shorter than this can never
produce a clip, so it gets its own category."""
HOLE_SECONDS = 20.0
"""How long the gap between two adjacent clips must be to count as a hole. A stretch with no clips
at all but with dialogue inside means a whole scene is missing, not just a few lines."""


def align_to_segments(lines: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[float, int]:
    """The offset of the subtitles relative to the audio, and the number of clips that fall
    completely inside a subtitle line at that offset.

    Clips whose edges were not trimmed by speech detection during cutting have boundaries equal to
    the subtitle line boundaries. So the start difference between a clip and a line (and the end
    difference likewise) piles up into a sharp peak at the true offset, and taking the mode finds
    it. Do not pick the offset as "the offset with the most clips inside lines": the boundary
    tolerance gives a whole range of offsets the same hit count, so that only finds the range,
    not the exact position.
    """
    if not lines or not rows:
        return 0.0, 0
    votes: Counter[int] = Counter()
    for row in rows:
        for line in lines:
            for difference in (row["start"] - line["start"], row["end"] - line["end"]):
                if abs(difference) <= SEARCH_SECONDS:
                    votes[round(difference / STEP)] += 1
    offset = round(votes.most_common(1)[0][0] * STEP, 3) if votes else 0.0
    inside = sum(
        any(
            line["start"] + offset - EDGE <= row["start"]
            and row["end"] <= line["end"] + offset + EDGE
            for line in lines
        )
        for row in rows
    )
    return offset, inside


def uncovered_lines(
    lines: list[dict[str, Any]], rows: list[dict[str, Any]], offset: float
) -> list[dict[str, Any]]:
    """Dialogue lines that no clip overlaps, sorted by whether they are shorter than the
    clip-cutting minimum length."""
    out = []
    for index, line in enumerate(lines):
        start, end = line["start"] + offset, line["end"] + offset
        if any(row["start"] < end and row["end"] > start for row in rows):
            continue
        seconds = round(end - start, 3)
        out.append(
            {
                "line": index,
                "start": round(start, 3),
                "end": round(end, 3),
                "stamp": stamp(start),
                "seconds": seconds,
                "text": line["text"],
                # A line shorter than the minimum cannot yield a valid clip. Only the longer
                # ones raise the question of why detection did not find the vocals.
                "reason": "below_floor" if seconds < FLOOR else "no_speech_found",
            }
        )
    return out


def find_holes(rows: list[dict[str, Any]], missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stretches with no clips in a row, but with dialogue inside.

    Missing a single line now and then is a detection boundary problem. A whole scene with no clips
    is a different matter, and it is worth checking first. Listening to over a hundred lines one by
    one is slow and shows no pattern. Holes are obvious at a glance, and they also help spot
    stretches like an opening theme that have no dialogue to begin with.
    """
    ordered = sorted(rows, key=lambda row: row["start"])
    holes = []
    for before, after in pairwise(ordered):
        if after["start"] - before["end"] < HOLE_SECONDS:
            continue
        inside = [e for e in missing if e["start"] >= before["end"] and e["end"] <= after["start"]]
        if not inside:
            continue
        holes.append(
            {
                "start": round(before["end"], 3),
                "end": round(after["start"], 3),
                "stamp": stamp(before["end"]),
                "seconds": round(after["start"] - before["end"], 3),
                "lines": len(inside),
                "dialogue_seconds": round(sum(e["seconds"] for e in inside), 3),
                "texts": [e["text"] for e in inside],
            }
        )
    return holes


def coverage(directory: Path, subtitle: Path, out: Path, pad: float = 0.0) -> dict[str, Any]:
    """Check dialogue coverage for this episode, and cut the lines that have no clip into audio
    files, grouped by reason."""
    import soundfile as sf

    from avs.labeling import _cut
    from avs.stages.subtitle import load_dialogue

    if out.exists():
        raise ValueError(
            f"Output already exists. Use another directory to keep the previous result: {out}"
        )
    if not math.isfinite(pad) or pad < 0:
        raise ValueError("Padding before and after must be a number of seconds, not less than 0")
    episode, rows = load_episode(directory)
    lines = load_dialogue(subtitle)
    if not lines:
        raise ValueError(f"{subtitle} has no dialogue lines. Check the subtitle style name")
    offset, inside = align_to_segments(lines, rows)
    if inside < len(rows) * 0.9:
        raise ValueError(
            f"Only {inside}/{len(rows)} clips fall inside subtitle lines. "
            "This subtitle file is most likely not for this episode"
        )

    missing = uncovered_lines(lines, rows, offset)
    duration = sf.info(episode["vocals"]).duration
    for entry in missing:
        folder = out / entry["reason"]
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{entry['line']:04d}_{entry['stamp'].replace(':', '-')}.wav"
        entry["file"] = f"{entry['reason']}/{name}"
        _cut(
            sf,
            episode["vocals"],
            max(0.0, entry["start"] - pad),
            min(duration, entry["end"] + pad),
            out / entry["file"],
        )

    holes = find_holes(rows, missing)
    for index, hole in enumerate(holes):
        (out / "holes").mkdir(parents=True, exist_ok=True)
        hole["file"] = f"holes/{index:02d}_{hole['stamp'].replace(':', '-')}.wav"
        _cut(sf, episode["vocals"], hole["start"], min(duration, hole["end"]), out / hole["file"])

    report = {
        "schema": "avs.coverage.v1",
        "episode": episode["name"],
        "subtitle": str(subtitle.resolve()),
        "offset_seconds": offset,
        "segments_inside_lines": f"{inside}/{len(rows)}",
        "pad_seconds": pad,
        "floor_seconds": FLOOR,
        "summary": {
            "dialogue_lines": len(lines),
            "lines_with_clip": len(lines) - len(missing),
            "lines_without_clip": len(missing),
            "below_floor": sum(e["reason"] == "below_floor" for e in missing),
            "no_speech_found": sum(e["reason"] == "no_speech_found" for e in missing),
            "clips": len(rows),
            "holes": len(holes),
            "hole_seconds": round(sum(h["seconds"] for h in holes), 3),
            "hole_dialogue_seconds": round(sum(h["dialogue_seconds"] for h in holes), 3),
        },
        "holes": holes,
        "uncovered": missing,
        "note": "The offset is the mode of the boundary differences between clips and subtitle "
        "lines. below_floor means the line itself is shorter than the clip-cutting minimum length. "
        "no_speech_found means the line is long enough but no clip was cut from it. "
        "The exact cause can only be known by listening to the audio.",
    }
    write_json(out / "report.json", report)
    listing = [
        f"{e['stamp']}  {e['seconds']:>5.2f}s  {e['reason']:<16}  {e['text']}" for e in missing
    ]
    (out / "lines.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    spans = []
    for hole in holes:
        spans.append(
            f"{hole['stamp']}  hole {hole['seconds']:.1f}s  "
            f"{hole['lines']} dialogue lines {hole['dialogue_seconds']:.1f}s  {hole['file']}"
        )
        spans.extend(f"      {text}" for text in hole["texts"])
    (out / "holes.txt").write_text("\n".join(spans) + "\n", encoding="utf-8")
    return report
