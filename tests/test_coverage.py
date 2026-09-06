"""对白覆盖核对：偏移靠现有片段反推，没片段的台词按原因分开。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.evaluation.coverage import (
    align_to_segments,
    coverage,
    find_holes,
    uncovered_lines,
)
from avs.project import segment_rows, write_json

# 字幕整体比音轨晚 0.5 秒，正确偏移是 -0.5。
SHIFT = 0.5
COVERED = [(0.0, 2.0), (2.0, 4.0), (8.0, 10.0)]
SHORT = (4.5, 5.0)
LONG = (5.5, 7.0)


def make_episode(root: Path) -> Path:
    directory = root / "ep1"
    directory.mkdir()
    vocals = directory / "ep1.wav"
    sf.write(vocals, np.zeros(44100 * 12, dtype=np.float32), 44100)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(b"fixture")
    write_json(
        directory / "episode.json",
        {
            "schema": "avs.episode.v1",
            "name": "ep1",
            "vocals": str(vocals),
            "analysis": str(analysis),
            "source": str(vocals),
            "sample_rate": 44100,
        },
    )
    spans = [{"start": s, "end": e} for s, e in COVERED]
    write_json(directory / "segments.json", segment_rows("ep1", spans))
    return directory


def make_subtitle(path: Path) -> Path:
    import pysubs2

    subs = pysubs2.SSAFile()
    for index, (start, end) in enumerate([*COVERED, SHORT, LONG]):
        subs.append(
            pysubs2.SSAEvent(
                start=int((start + SHIFT) * 1000),
                end=int((end + SHIFT) * 1000),
                text=f"第 {index} 句",
            )
        )
    subs.save(str(path))
    return path


def test_offset_comes_from_where_the_clips_fall_inside_the_lines(tmp_path: Path) -> None:
    directory = make_episode(tmp_path)
    lines = [{"start": s + SHIFT, "end": e + SHIFT, "text": ""} for s, e in COVERED]
    rows = [{"start": s, "end": e} for s, e in COVERED]
    offset, inside = align_to_segments(lines, rows)
    assert (offset, inside) == (-SHIFT, len(rows))
    assert align_to_segments([], rows) == (0.0, 0)
    assert directory.exists()


def test_uncovered_lines_split_by_the_one_second_floor(tmp_path: Path) -> None:
    rows = [{"start": s, "end": e} for s, e in COVERED]
    lines = [
        {"start": s + SHIFT, "end": e + SHIFT, "text": "x"} for s, e in [*COVERED, SHORT, LONG]
    ]
    missing = uncovered_lines(lines, rows, -SHIFT)
    assert [e["reason"] for e in missing] == ["below_floor", "no_speech_found"]
    assert [e["seconds"] for e in missing] == [0.5, 1.5]
    assert [e["stamp"] for e in missing] == ["00:04.50", "00:05.50"]
    assert tmp_path.exists()


def test_coverage_cuts_the_missing_lines_and_refuses_a_foreign_subtitle(tmp_path: Path) -> None:
    directory = make_episode(tmp_path)
    subtitle = make_subtitle(tmp_path / "ep1.ass")
    out = tmp_path / "coverage"

    report = coverage(directory, subtitle, out, pad=0.2)
    assert report["offset_seconds"] == -SHIFT
    assert report["summary"] == {
        "dialogue_lines": 5,
        "lines_with_clip": 3,
        "lines_without_clip": 2,
        "below_floor": 1,
        "no_speech_found": 1,
        "clips": 3,
        "holes": 0,
        "hole_seconds": 0,
        "hole_dialogue_seconds": 0,
    }
    cut = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.wav"))
    assert [e["file"] for e in report["uncovered"]] == cut
    # 留白让切出来的音频比字幕行长 0.4 秒，方便听清开头结尾。
    assert sf.info(out / cut[0]).duration == pytest.approx(0.9, abs=0.02)
    assert "第 3 句" in (out / "lines.txt").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="已存在"):
        coverage(directory, subtitle, out)

    other = make_subtitle(tmp_path / "other.ass")
    import pysubs2

    subs = pysubs2.load(str(other))
    for event in subs:
        event.start += 60_000
        event.end += 60_000
    subs.save(str(other))
    with pytest.raises(ValueError, match="多半不是这一集"):
        coverage(directory, other, tmp_path / "coverage-other")


def test_holes_are_stretches_with_no_clip_but_real_dialogue(tmp_path: Path) -> None:
    # 片段之间留一个 30 秒的空档，里面放两条台词，另一个空档里什么都没有。
    rows = [{"start": 0.0, "end": 2.0}, {"start": 32.0, "end": 34.0}, {"start": 70.0, "end": 72.0}]
    missing = [
        {"start": 5.0, "end": 6.5, "seconds": 1.5, "text": "第一句"},
        {"start": 20.0, "end": 21.0, "seconds": 1.0, "text": "第二句"},
    ]
    holes = find_holes(rows, missing)
    assert [h["stamp"] for h in holes] == ["00:02.00"]
    assert holes[0]["lines"] == 2
    assert holes[0]["dialogue_seconds"] == 2.5
    assert holes[0]["texts"] == ["第一句", "第二句"]
    # 34 到 70 秒同样是空档，但里面没有台词，不算问题。
    assert len(holes) == 1
    assert tmp_path.exists()


def test_coverage_writes_hole_audio_and_listing(tmp_path: Path) -> None:
    directory = make_episode(tmp_path)
    subtitle = make_subtitle(tmp_path / "ep1.ass")
    out = tmp_path / "coverage"
    report = coverage(directory, subtitle, out)
    # 片段 4 秒到 8 秒之间只空了 4 秒，够不上空洞门槛。
    assert report["summary"]["holes"] == 0
    assert (out / "holes.txt").read_text(encoding="utf-8").strip() == ""
