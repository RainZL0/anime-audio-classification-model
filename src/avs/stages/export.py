"""按分好的组导出成品 wav，一组一个目录。

**这一步有一个绝对不能犯的错**：切片必须回到**原始采样率的人声轨**上去切，不能拿 16 kHz
的分析副本。音色模型大多在 40 到 48 kHz 上训练，拿 16 kHz 升采样回去当成品，高频信息已经
永久丢了，补不回来。麻烦的是这种损坏**听着不明显、程序也不报错**，可能训完一个音色模型才
发现效果不对还查不出原因。所以这里会**主动检查采样率**，低于 32 kHz 直接报错不导。

**响度统一，但不能压到破音。** 用的是广播那套 ITU-R BS.1770 的响度算法（`pyloudnorm`），
不是简单的音量平均 —— 后者会让安静的耳语和大喊听起来差很多。调完之后如果峰值要溢出，就
整体压回去，宁可这一条响度差一点，也不要削顶。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_LUFS = -23.0
"""统一到这个响度，单位 LUFS。-23 是广播标准，留了充足的余量不至于破音。"""

PEAK_CEILING = -1.0
"""调完响度之后峰值不许超过这个值，单位 dBFS。超了就整体压回去。"""

MIN_SAMPLE_RATE = 32_000
"""人声轨低于这个采样率就拒绝导出，见模块开头那段。"""

MIN_LOUDNESS_SECONDS = 0.4
"""短于这个长度算不出可靠的响度，那一条就不调响度，原样导出。单位秒。"""


@dataclass(frozen=True)
class Written:
    """导出的一条成品。"""

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
    """把一段音频调到目标响度，峰值溢出就压回去。返回（音频, 原来的响度, 加了多少分贝）。"""
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
    """把分好的组切出来写成 wav。`vocals` 是「集名 -> 那一集的原始采样率人声轨」。

    一组一个目录，文件名带集数和时间点，这样出问题能一眼回溯到源头。
    """
    import numpy as np
    import soundfile as sf

    for episode, path in vocals.items():
        rate = sf.info(str(path)).samplerate
        if rate < MIN_SAMPLE_RATE:
            raise ValueError(
                f"{episode} 的人声轨是 {rate} Hz，低于 {MIN_SAMPLE_RATE} Hz。"
                "成品必须从原始采样率的音轨上切，不能用 16 kHz 的分析副本"
            )

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
            out = folder / f"{clip.episode}_{clip.start:08.2f}.wav"
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


def write_manifest(written: list[Written], out_dir: Path) -> Path:
    """写一张表，记录每条成品是从哪来的。

    出了问题能顺着它查回去 —— 哪一集、第几秒、响度调了多少。用 parquet 是因为它自带列
    的类型，不像 csv 那样什么都变成字符串。
    """
    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "speaker": w.name,
                "file": w.path.name,
                "episode": w.episode,
                "start": w.start,
                "end": w.end,
                "duration": round(w.duration, 3),
                "lufs_before": w.lufs_before,
                "gain_db": w.gain_db,
            }
            for w in written
        ]
    )
    path = out_dir / "manifest.parquet"
    frame.to_parquet(path, index=False)
    return path


def summarize(written: list[Written]) -> dict[str, Any]:
    """导出来多少东西，按组分。"""
    from collections import defaultdict

    per: dict[str, list[float]] = defaultdict(list)
    for w in written:
        per[w.name].append(w.duration)
    rows = [
        {"speaker": name, "clips": len(v), "total_sec": round(sum(v), 1)} for name, v in per.items()
    ]
    rows.sort(key=lambda r: (r["speaker"] == "_misc", -float(str(r["total_sec"]))))
    return {
        "files": len(written),
        "total_sec": round(sum(w.duration for w in written), 1),
        "speakers": rows,
    }
