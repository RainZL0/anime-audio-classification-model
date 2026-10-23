"""Tests for the export step.

**This guards against the one error in this project that you cannot hear, that
gives no warning, and that still ruins the final output**: cutting the final
clips from the 16 kHz analysis copy. Voice models are mostly trained at 40 to
48 kHz, and lost high frequencies cannot be restored. You may only notice
after training a voice model. So refusing low sample rates must be locked down.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.stages.export import PEAK_CEILING, export, summarize


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
    """The 16 kHz analysis copy must be blocked. This is the line between a usable
    and a ruined output."""
    analysis = tmp_path / "analysis_16k.wav"
    _tone(analysis, 16_000)
    with pytest.raises(ValueError, match="16000"):
        export(
            {"speaker_01": [Clip("ep01", "A", 0.0, 2.0)]},
            {"ep01": analysis},
            tmp_path / "out",
        )


def test_output_keeps_the_source_sample_rate(tmp_path: Path) -> None:
    """The output sample rate must match the vocals track. It must not change silently."""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 1.0, 3.0)]}, {"ep01": vocals}, tmp_path / "out"
    )
    assert sf.info(str(written[0].path)).samplerate == 44_100


def test_loudness_is_evened_out_across_clips(tmp_path: Path) -> None:
    """A loud clip and a quiet clip should come out at about the same loudness.
    Otherwise the dataset sounds uneven."""
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
    assert max(levels) / min(levels) < 1.5  # The original levels differ by 25 times
    assert all(w.gain_db != 0.0 for w in written)


def test_never_clips_the_peak(tmp_path: Path) -> None:
    """Adjusting loudness is fine, but clipping the peaks is not.
    It is better for this clip to stay a bit uneven."""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100, level=0.99)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 0.5, 5.5)]}, {"ep01": vocals}, tmp_path / "out"
    )
    peak = float(np.max(np.abs(sf.read(str(written[0].path))[0])))
    assert peak <= 10.0 ** (PEAK_CEILING / 20.0) + 1e-3


def test_very_short_clips_are_left_alone(tmp_path: Path) -> None:
    """A clip that is too short gives no reliable loudness reading. So leave it
    alone: exporting it as it is beats adjusting it blindly."""
    vocals = tmp_path / "vocals.flac"
    _tone(vocals, 44_100)
    written = export(
        {"speaker_01": [Clip("ep01", "A", 0.0, 0.2)]}, {"ep01": vocals}, tmp_path / "out"
    )
    assert written[0].lufs_before is None
    assert written[0].gain_db == 0.0


def test_summary_puts_unassigned_last(tmp_path: Path) -> None:
    """`_unassigned` holds clips with no assigned speaker. It goes last, so it
    does not take the place of a main character."""
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
