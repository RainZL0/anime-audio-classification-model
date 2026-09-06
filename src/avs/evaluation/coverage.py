"""对白覆盖核对：字幕里有哪些台词根本没有对应片段，把它们切出来听。

片段来自「字幕范围 ∩ 检测到有人说话」，还带一个 1 秒下限，所以片段数远少于字幕对白行数。
少掉的那些是听不到、检测漏了，还是本来就该丢，只能人耳判断，这里负责把它们摆到面前。

字幕相对音轨的偏移不再靠语音检测重算：现有片段都是从字幕切出来的，边界差的众数就是偏移，
既不需要原始检测结果，也和当初切段用的是同一套边界。
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
"""判断片段是否落在字幕行内时容许的边界误差，覆盖毫秒取整。"""
FLOOR = 1.0
"""当初切段的时长下限；短于它的字幕行不可能切出片段，单独归一类。"""
HOLE_SECONDS = 20.0
"""相邻片段间隔多久算一个空洞。整段没有片段而里面有台词，说明丢的是整场戏，不是零星几句。"""


def align_to_segments(lines: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[float, int]:
    """字幕相对音轨的偏移，以及在该偏移下完整落在字幕行内的片段数。

    切段时语音检测没有削掉边的那些片段，边界就等于字幕行边界，所以片段与行的起点差
    （终点差同理）会在真实偏移上堆成一个很尖的峰，取众数即可。不用「落在行内的片段最多」
    直接定偏移：边界容差让一整段偏移都拿到同样的命中数，只能挑出这段区间，挑不准位置。
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
    """没有任何片段与之重叠的对白行，按是否短于切段下限分类。"""
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
                # 短于下限的行不可能切出合格片段，长的那些才需要问检测为什么没认出人声。
                "reason": "below_floor" if seconds < FLOOR else "no_speech_found",
            }
        )
    return out


def find_holes(rows: list[dict[str, Any]], missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """连续没有片段、里面却有台词的整段。

    零星漏一句是检测边界问题，整场戏没有片段是另一回事，值得先看后者：一百多条逐条听
    既慢又看不出规律，而空洞一目了然，还能顺带认出片头曲这种本来就没对白的段落。
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
    """核对这一集的对白覆盖，把没片段的台词按原因切成音频。"""
    import soundfile as sf

    from avs.labeling import _cut
    from avs.stages.subtitle import load_dialogue

    if out.exists():
        raise ValueError(f"输出已存在，换个目录以保留上次结果：{out}")
    if not math.isfinite(pad) or pad < 0:
        raise ValueError("前后留白必须是不小于 0 的秒数")
    episode, rows = load_episode(directory)
    lines = load_dialogue(subtitle)
    if not lines:
        raise ValueError(f"{subtitle} 里没有对白行，检查字幕样式名")
    offset, inside = align_to_segments(lines, rows)
    if inside < len(rows) * 0.9:
        raise ValueError(f"只有 {inside}/{len(rows)} 条片段落在字幕行内，这份字幕多半不是这一集")

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
        "note": "偏移取片段与字幕行边界差的众数；below_floor 是行本身短于切段下限，"
        "no_speech_found 是行够长却没切出片段，具体原因要听音频才知道。",
    }
    write_json(out / "report.json", report)
    listing = [
        f"{e['stamp']}  {e['seconds']:>5.2f}s  {e['reason']:<16}  {e['text']}" for e in missing
    ]
    (out / "lines.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    spans = []
    for hole in holes:
        spans.append(
            f"{hole['stamp']}  空 {hole['seconds']:.1f}s  "
            f"台词 {hole['lines']} 行 {hole['dialogue_seconds']:.1f}s  {hole['file']}"
        )
        spans.extend(f"      {text}" for text in hole["texts"])
    (out / "holes.txt").write_text("\n".join(spans) + "\n", encoding="utf-8")
    return report
