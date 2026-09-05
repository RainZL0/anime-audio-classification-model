"""把说话人分段的原始输出，整理成能真正拿去导出的候选片段。

为什么需要这一步：直接拿 pyannote 的输出去切，切出来的片段里经常混着别人的声音。
第 1 集的实测（`runs/probe/ep01/`）说明了原因：

- 单段中位数只有 0.3 到 1.1 秒，全集 514 段里够 1 秒的只有 226 段；
- 514 段里有 225 段（44%）与前一段「换了人、且间隔不到 0.25 秒」。

在这种快问快答式的对话上，说话人分段本身 100 到 200 毫秒的边界误差就足以把邻座的
声音切进成品，而模型标出来的「重叠」只有 2%，远少于实际听到的。所以这一步做四件事：
减掉重叠、合并同一人的相邻碎段、在换人处向内让出安全距离、按时长筛一遍。

一个必须写下来的坑：pyannote 的 `exclusive_speaker_diarization` **不是**「没有重叠
的音频」。它的构造方式是把同时说话人数强行截到 1（源码里的 `np.minimum(count, 1)`），
也就是把重叠帧判给其中一个人，音频里另一个人还在。它只保证**标签**不重叠。所以这里
拿它当基准之后，还要用非排他标注算出来的重叠区间去减。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

# 下面这些默认值都是照第 1 集的实测定的，换素材要重新看
MERGE_GAP = 0.30
"""同一个人相邻两段间隔小于这个值就合并，单位秒。"""

REQUIRED_MARGIN = 0.35
"""片段首尾离「别人在说话」至少要留出的距离，单位秒。

不够就向内缩到够为止，缩完太短就淘汰。注意是向内缩，不是向外扩：在紧邻换人的素材上
外扩余量等于主动把邻座的声音裹进成品。0.35 秒是照说话人分段 100 到 300 毫秒的常见
边界误差定的。
"""

OVERLAP_MARGIN = 0.10
"""重叠区间往两边各扩这么多再减掉，因为重叠检测本身也有边界误差，单位秒。"""

MIN_DURATION = 1.0
MAX_DURATION = 12.0
SONG_MIN_DURATION = 15.0
"""超过这个长度的连续单人段基本都是唱歌，实测 OP 就是一段 47 秒的，单位秒。"""


@dataclass(frozen=True)
class Segment:
    """一个候选片段。时间是相对原始音轨的秒数。"""

    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _speaker_segments(annotation: Any, label: str) -> list[tuple[float, float]]:
    return [(float(s.start), float(s.end)) for s in annotation.label_timeline(label)]


def _merge_adjacent(
    segments: list[tuple[float, float]],
    others: list[tuple[float, float]],
    merge_gap: float,
) -> list[tuple[float, float]]:
    """合并同一个人的相邻碎段，但缝隙里有别人说话就不合并。"""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(segments):
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        gap = start - prev_end
        interrupted = any(o_start < start and o_end > prev_end for o_start, o_end in others)
        if 0 <= gap <= merge_gap and not interrupted:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _enforce_margin(
    segment: tuple[float, float],
    others: list[tuple[float, float]],
    required: float,
) -> tuple[float, float]:
    """把首尾向内缩到离别人说话至少 required 秒。缩过头会变成负长度，交给后面淘汰。"""
    start, end = segment
    prev_end = max((o_end for _, o_end in others if o_end <= start), default=None)
    if prev_end is not None and start - prev_end < required:
        start = prev_end + required
    next_start = min((o_start for o_start, _ in others if o_start >= end), default=None)
    if next_start is not None and next_start - end < required:
        end = next_start - required
    return start, end


def build_segments(
    diarization: Any,
    exclusive: Any,
    merge_gap: float = MERGE_GAP,
    required_margin: float = REQUIRED_MARGIN,
    overlap_margin: float = OVERLAP_MARGIN,
    min_duration: float = MIN_DURATION,
    max_duration: float = MAX_DURATION,
    song_min_duration: float = SONG_MIN_DURATION,
) -> tuple[list[Segment], dict[str, Any]]:
    """整理出候选片段，并返回一份「谁被淘汰、为什么」的账。

    diarization 是非排他标注，用来找重叠区间；exclusive 是排他标注，当切段基准。
    """
    from pyannote.core import Segment as PSegment
    from pyannote.core import Timeline

    overlap = diarization.get_overlap()
    padded = Timeline(
        [PSegment(max(0.0, s.start - overlap_margin), s.end + overlap_margin) for s in overlap]
    ).support()

    # 前面几项是段数，末尾两项是秒数，所以值类型放宽到 float
    counts: dict[str, float] = {
        "raw": 0,
        "after_overlap_removal": 0,
        "after_merge": 0,
        "dropped_overlap": 0,
        "dropped_too_short": 0,
        "dropped_too_long": 0,
        "suspected_song": 0,
        "trimmed": 0,
        "kept": 0,
    }

    kept: list[Segment] = []
    songs: list[Segment] = []
    for label in exclusive.labels():
        raw = _speaker_segments(exclusive, label)
        counts["raw"] += len(raw)

        clean_timeline = Timeline([PSegment(s, e) for s, e in raw]).extrude(padded)
        clean = [(float(s.start), float(s.end)) for s in clean_timeline]
        counts["after_overlap_removal"] += len(clean)
        counts["dropped_overlap"] += max(0, len(raw) - len(clean))

        # 风险来源必须用非排他标注：排他标注把重叠帧判给了其中一个人，
        # 拿它算「邻座在哪」会漏掉正是最危险的那部分。
        others = [
            seg
            for other in diarization.labels()
            if other != label
            for seg in _speaker_segments(diarization, other)
        ]
        merged = _merge_adjacent(clean, others, merge_gap)
        counts["after_merge"] += len(merged)

        for candidate in merged:
            start, end = _enforce_margin(candidate, others, required_margin)
            if (start, end) != candidate:
                counts["trimmed"] += 1
            duration = end - start
            if duration >= song_min_duration:
                counts["suspected_song"] += 1
                songs.append(Segment(str(label), start, end))
            elif duration < min_duration:
                counts["dropped_too_short"] += 1
            elif duration > max_duration:
                counts["dropped_too_long"] += 1
            else:
                counts["kept"] += 1
                kept.append(Segment(str(label), start, end))

    kept.sort(key=lambda s: s.start)
    counts["kept_sec"] = round(sum(s.duration for s in kept), 1)
    counts["song_sec"] = round(sum(s.duration for s in songs), 1)
    return kept, {"counts": counts, "songs": [(s.speaker, s.start, s.end) for s in songs]}


def adjacency_rate(segments: list[Segment], gap: float = 0.25) -> float:
    """有多大比例的片段，紧挨着前一段而且换了人。这个数字越高，串音风险越大。"""
    if not segments:
        return 0.0
    ordered = sorted(segments, key=lambda s: s.start)
    close = sum(1 for a, b in pairwise(ordered) if a.speaker != b.speaker and b.start - a.end < gap)
    return close / len(ordered)
