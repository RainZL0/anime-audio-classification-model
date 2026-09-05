"""导出那一步的测试。

**这里防的是这个项目唯一一个「听不出来、也不报错、但会毁掉成品」的错**：拿 16 kHz 的分析
副本去切成品。音色模型大多在 40 到 48 kHz 上训练，高频丢了补不回来，而且可能训完一个音色
模型才发现不对。所以拒绝低采样率这条必须钉死。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.stages.export import PEAK_CEILING, TARGET_LUFS, export, summarize, write_manifest


@dataclass(frozen=True)
class Clip:
    episode: str
    local: str
    start: float
    end: float


def _tone(path: Path, sample_rate: int, seconds: float = 6.0, level: float = 0.1) -> None:
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    sf.write(str(path), (level * np.sin(2 * np.pi * 220 * t)).astype("float32"), sample_rate)


def test_refuses_to_cut_from_a_low_rate_track(tmp_path: Path) -> None:
    """16 kHz 的分析副本必须被挡住，这是成品的生死线。"""
    analysis = tmp_path / "analysis_16k.wav"
    _tone(analysis, 16_000)
    with pytest.raises(ValueError, match="16000"):
        export(
            {"speaker_01": [Clip("ep01", "A", 0.0, 2.0)]},
            {"ep01": analysis},
            tmp_path / "out",
        )


def test_output_keeps_the_source_sample_rate(tmp_path: Path) -> None:
    """成品的采样率必须跟人声轨一样，不能悄悄变。"""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 1.0, 3.0)]}, {"ep01": vocals}, tmp_path / "out"
    )
    assert sf.info(str(written[0].path)).samplerate == 44_100


def test_loudness_is_evened_out_across_clips(tmp_path: Path) -> None:
    """一大声一小声的两条，导出来响度应该拉到差不多，否则数据集听着忽大忽小。"""
    loud, quiet = tmp_path / "loud.flac", tmp_path / "quiet.flac"
    _tone(loud, 44_100, level=0.5)
    _tone(quiet, 44_100, level=0.02)
    written = export(
        {
            "speaker_01": [Clip("loud", "A", 0.5, 5.5)],
            "speaker_02": [Clip("quiet", "A", 0.5, 5.5)],
        },
        {"loud": loud, "quiet": quiet},
        tmp_path / "out",
    )
    levels = [float(np.sqrt(np.mean(sf.read(str(w.path))[0] ** 2))) for w in written]
    assert max(levels) / min(levels) < 1.5  # 原始差了 25 倍
    assert all(w.gain_db != 0.0 for w in written)


def test_never_clips_the_peak(tmp_path: Path) -> None:
    """调响度可以，削顶不行。宁可这一条响度差一点。"""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100, level=0.99)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 0.5, 5.5)]}, {"ep01": vocals}, tmp_path / "out"
    )
    peak = float(np.max(np.abs(sf.read(str(written[0].path))[0])))
    assert peak <= 10.0 ** (PEAK_CEILING / 20.0) + 1e-3


def test_very_short_clips_are_left_alone(tmp_path: Path) -> None:
    """太短算不出可靠的响度，那就别调，原样导出比瞎调好。"""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 0.0, 0.2)]}, {"ep01": vocals}, tmp_path / "out"
    )
    assert written[0].lufs_before is None
    assert written[0].gain_db == 0.0


def test_manifest_records_where_each_file_came_from(tmp_path: Path) -> None:
    """出了问题要能顺着表查回去：哪一集、第几秒、响度调了多少。"""
    import pandas as pd

    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    out = tmp_path / "out"
    written = export({"speaker_01": [Clip("ep01", "A", 1.0, 4.0)]}, {"ep01": vocals}, out)
    frame = pd.read_parquet(write_manifest(written, out))
    row = frame.iloc[0]
    assert row["speaker"] == "speaker_01"
    assert row["episode"] == "ep01"
    assert row["start"] == 1.0
    assert row["duration"] == 3.0
    assert TARGET_LUFS - 30 < row["lufs_before"] < 0


def test_summary_puts_unassigned_last(tmp_path: Path) -> None:
    """`_unassigned` 是未归属片段，排在最后，别让它抢主角的位置。"""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    written = export(
        {
            "_unassigned": [Clip("ep01", "A", 0.0, 5.0)],
            "speaker_01": [Clip("ep01", "A", 0.0, 2.0)],
        },
        {"ep01": vocals},
        tmp_path / "out",
    )
    report = summarize(written)
    assert [r["speaker"] for r in report["speakers"]] == ["speaker_01", "_unassigned"]
