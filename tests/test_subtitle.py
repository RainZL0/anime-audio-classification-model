"""按字幕切片段这一步的测试。

要防住的头号风险是**安静的错位**：字幕跟音轨对不上的时候，程序不会报错，只会把每一段都
切到错的位置，而切错的片段听着仍然像一句话，人很难发现。所以对齐和它的兜底检查是这里
测得最重的部分。
"""

from __future__ import annotations

from dataclasses import dataclass

from avs.stages.subtitle import (
    MIN_PIECE,
    find_offset,
    split_segments,
    summarize,
)


@dataclass(frozen=True)
class Row:
    """一条候选片段，长得跟 segments.json 里的一行一样。"""

    speaker: str
    start: float
    end: float


def _rows(*spans: tuple[float, float, str]) -> list[dict[str, object]]:
    return [{"speaker": who, "start": a, "end": b} for a, b, who in spans]


def test_one_clip_two_subtitle_lines_becomes_two_pieces() -> None:
    """这是整件事的核心：一条片段横跨两行字幕，说明里面有两句话，要切成两段。"""
    lines = [(0.0, 2.0), (3.0, 5.0)]
    pieces, dropped = split_segments(_rows((0.0, 5.0, "SPEAKER_01")), lines)
    assert [(p.start, p.end) for p in pieces] == [(0.0, 2.0), (3.0, 5.0)]
    assert all(p.speaker == "SPEAKER_01" for p in pieces)
    assert dropped == []


def test_the_gap_between_lines_is_thrown_away() -> None:
    """两行字幕之间的空隙不要，那里多半正是换人的地方。"""
    pieces, _ = split_segments(_rows((0.0, 10.0, "A")), [(0.0, 2.0), (8.0, 10.0)])
    assert sum(p.duration for p in pieces) == 4.0


def test_clips_outside_every_line_come_back_instead_of_vanishing() -> None:
    """完全落在字幕之外的片段要退回来，不能安静地消失。

    那些多半是惊呼、笑声、喘息 —— 字幕里没有，但对音色有用，怎么处置由调用方决定。
    """
    rows = _rows((0.0, 2.0, "A"), (50.0, 52.0, "B"))
    pieces, dropped = split_segments(rows, [(0.0, 2.0)])
    assert len(pieces) == 1
    assert dropped == [rows[1]]


def test_pieces_shorter_than_the_floor_are_not_kept() -> None:
    """切出来的碎片短于门槛就不要，因为短片段算不出可靠的声音指纹。"""
    pieces, _ = split_segments(_rows((0.0, 10.0, "A")), [(0.0, 0.5), (2.0, 6.0)])
    assert [(p.start, p.end) for p in pieces] == [(2.0, 6.0)]
    assert all(p.duration >= MIN_PIECE for p in pieces)


def test_offset_is_measured_not_assumed() -> None:
    """字幕比音轨早 1 秒时，要量出 -1 秒这个偏移，把字幕挪回去。"""
    speech = [(10.0, 12.0), (20.0, 23.0), (30.0, 31.5)]
    lines = [(a + 1.0, b + 1.0) for a, b in speech]
    offset, overlap = find_offset(lines, speech, 40.0)
    assert abs(offset + 1.0) < 0.05
    assert overlap > 0.9


def test_offset_of_zero_when_already_aligned() -> None:
    """本来就对得上的时候不要乱挪。"""
    speech = [(5.0, 8.0), (15.0, 19.0)]
    offset, overlap = find_offset(speech, speech, 30.0)
    assert abs(offset) < 0.05
    assert overlap > 0.95


def test_wrong_subtitles_show_up_as_a_low_overlap() -> None:
    """拿错集数的字幕必须能从重合度上看出来，这是防安静错位的那道闸。"""
    speech = [(10.0, 12.0), (20.0, 23.0)]
    unrelated = [(40.0, 40.5), (60.0, 60.5)]
    _, overlap = find_offset(unrelated, speech, 90.0)
    assert overlap < 0.6


def test_summary_reports_what_was_lost() -> None:
    """产量账要能直接读出来：切完剩多少、退回多少。"""
    rows = _rows((0.0, 10.0, "A"), (50.0, 52.0, "B"))
    pieces, dropped = split_segments(rows, [(0.0, 4.0)])
    stats = summarize(pieces, dropped, rows, offset=0.0, overlap=0.8)
    assert stats["before"] == 2
    assert stats["before_sec"] == 12.0
    assert stats["after"] == 1
    assert stats["after_sec"] == 4.0
    assert stats["dropped"] == 1
    assert stats["kept_ratio"] == 0.3333
