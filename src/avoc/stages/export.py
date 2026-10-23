"""Export the labeled clips as finished wav files, one folder per character.

**This step has one mistake that must never be made.** Clips must be cut from the
**original-sample-rate vocal track**, not from the 16 kHz analysis copy. Most voice models are
trained at 40 to 48 kHz. If a 16 kHz file is upsampled and used as the finished output, the
high-frequency information is permanently lost and cannot be recovered. The trouble is that this
damage **is not obvious to the ear, and the program reports no error**. You could train a voice
model and only find out much later that the results are wrong, with no clear cause. So this step
**checks the sample rate** and refuses to export anything below 32 kHz.

**Loudness is unified, but without clipping.** It uses the broadcast loudness algorithm ITU-R
BS.1770 (through `pyloudnorm`), not a simple average volume, because a plain average makes a whisper
and a shout sound very different. After adjustment, if the peak would overflow, the whole clip is
scaled back down. It is better for one clip to be slightly off in loudness than to be clipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_LUFS = -23.0
"""Loudness to normalize to, in LUFS (a standard loudness unit). -23 is the broadcast standard, and
it leaves enough room to avoid clipping."""

PEAK_CEILING = -1.0
"""The peak must not exceed this after the loudness adjustment, in dBFS (decibels relative to full
scale). If it does, the whole clip is scaled back down."""

MIN_SAMPLE_RATE = 32_000
"""Vocal tracks below this sample rate are refused for export. See the note at the top of this
module."""

MIN_LOUDNESS_SECONDS = 0.4
"""Clips shorter than this cannot be measured reliably, so their loudness is left alone and they are
exported unchanged. In seconds."""


@dataclass(frozen=True)
class Written:
    """One exported file."""

    name: str
    path: Path
    episode: str
    start: float
    end: float
    lufs_before: float | None
    gain_db: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _normalize(mono: Any, sample_rate: int) -> tuple[Any, float | None, float]:
    """Adjust a piece of audio to the target loudness, and scale it back down if the peak overflows.
    Returns (audio, original loudness, gain added in dB)."""
    import numpy as np
    import pyloudnorm

    if len(mono) < MIN_LOUDNESS_SECONDS * sample_rate:
        return mono, None, 0.0

    meter = pyloudnorm.Meter(sample_rate)
    loudness = float(meter.integrated_loudness(mono))
    if not np.isfinite(loudness):
        return mono, None, 0.0

    gain_db = TARGET_LUFS - loudness
    scaled = mono * (10.0 ** (gain_db / 20.0))

    peak = float(np.max(np.abs(scaled))) if len(scaled) else 0.0
    ceiling = 10.0 ** (PEAK_CEILING / 20.0)
    if peak > ceiling:
        scaled = scaled * (ceiling / peak)
        gain_db += 20.0 * float(np.log10(ceiling / peak))
    return scaled, loudness, gain_db


def export(
    assigned: dict[str, list[Any]],
    vocals: dict[str, Path],
    out_dir: Path,
) -> list[Written]:
    """Cut the clips of each assigned group and write them as wav files. `vocals` maps "episode name
    -> that episode's original-sample-rate vocal track".

    One folder per group. File names include the episode and the time points, so any problem can be
    traced back to its source at a glance.
    """
    import numpy as np
    import soundfile as sf

    if not any(assigned.values()):
        raise ValueError("There are no clips to export")
    infos = {}
    for episode, path in vocals.items():
        infos[episode] = sf.info(str(path))
        rate = infos[episode].samplerate
        if rate < MIN_SAMPLE_RATE:
            raise ValueError(
                f"{episode} vocal track is {rate} Hz, below {MIN_SAMPLE_RATE} Hz. "
                "Finished files must be cut from the original sample rate track, not from the 16 "
                "kHz analysis copy"
            )

    for clips in assigned.values():
        for clip in clips:
            info = infos[clip.episode]
            if not (
                np.isfinite(clip.start)
                and np.isfinite(clip.end)
                and 0 <= clip.start < clip.end <= info.duration + 1 / info.samplerate
            ):
                raise ValueError("A clip is outside the time range of its vocal track")

    written: list[Written] = []
    for name, clips in assigned.items():
        folder = out_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        for clip in clips:
            path = vocals[clip.episode]
            info = sf.info(str(path))
            data, rate = sf.read(
                str(path),
                start=int(clip.start * info.samplerate),
                stop=int(clip.end * info.samplerate),
                always_2d=True,
                dtype="float32",
            )
            mono = data.mean(axis=1)
            scaled, before, gain = _normalize(mono, rate)
            out = folder / f"{clip.episode}_{clip.start:012.6f}_{clip.end:012.6f}.wav"
            sf.write(str(out), np.clip(scaled, -1.0, 1.0), rate, subtype="PCM_24")
            written.append(
                Written(
                    name=name,
                    path=out,
                    episode=clip.episode,
                    start=clip.start,
                    end=clip.end,
                    lufs_before=None if before is None else round(before, 2),
                    gain_db=round(gain, 2),
                )
            )
    return written


def summarize(written: list[Written]) -> dict[str, Any]:
    """How much was exported, per group."""
    from collections import defaultdict

    per: dict[str, list[float]] = defaultdict(list)
    for w in written:
        per[w.name].append(w.duration)
    rows = [
        {"speaker": name, "clips": len(v), "total_sec": round(sum(v), 1)} for name, v in per.items()
    ]
    rows.sort(key=lambda r: (r["speaker"] == "_unassigned", -float(str(r["total_sec"]))))
    return {
        "files": len(written),
        "total_sec": round(sum(w.duration for w in written), 1),
        "speakers": rows,
    }
