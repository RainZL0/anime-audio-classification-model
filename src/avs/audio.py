"""原采样率人声处理，以及只供分析使用的 16 kHz 副本。"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soundfile as sf

SEPARATION_MODEL = "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
PRECISIONS = {"fp32": "float32", "fp16": "float16", "bf16": "bfloat16"}
ANALYSIS_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class AudioInfo:
    """一个音频文件的基本参数。"""

    sample_rate: int
    channels: int
    duration: float


def audio_info(path: Path) -> AudioInfo:
    """读采样率、声道数、时长，不把音频载进内存。"""
    info = sf.info(str(path))
    return AudioInfo(
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        duration=float(info.frames) / float(info.samplerate),
    )


def _ffmpeg(args: list[str]) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("找不到 ffmpeg，先装上并加进 PATH")
    proc = subprocess.run(
        [exe, "-v", "error", "-y", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{proc.stderr.strip()[:500]}")


def extract_audio(video: Path, dst: Path) -> None:
    """从视频里抽出第一条音轨，无损存成 FLAC，采样率和声道都不动。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-i", str(video), "-vn", "-map", "0:a:0", "-c:a", "flac", str(dst)])


def separate_vocals(
    src: Path,
    out_dir: Path,
    models_dir: Path,
    sample_rate: int,
    model_filename: str = SEPARATION_MODEL,
    keep_instrumental: bool = False,
    precision: str = "fp16",
) -> Path:
    """抠人声。sample_rate 必须传源文件的采样率，否则库会默认按 44100 重采样。

    precision 取 fp32 / fp16 / bf16，默认 fp16，实测依据见 docs/TOOLS.md。低精度快得多，
    代价是输出和全精度有细微出入。audio-separator 调 autocast 时不指定 dtype，等于用
    torch 的全局默认值（CUDA 上是 fp16），所以想要 bf16 只能改那个默认值。
    """
    import torch
    from audio_separator.separator import Separator

    if precision not in PRECISIONS:
        raise ValueError(f"precision 只能是 {', '.join(PRECISIONS)}，收到 {precision}")

    out_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    if precision != "fp32":
        torch.set_autocast_dtype("cuda", getattr(torch, PRECISIONS[precision]))

    separator = Separator(
        log_level=logging.WARNING,
        model_file_dir=str(models_dir),
        output_dir=str(out_dir),
        output_format="FLAC",
        sample_rate=sample_rate,
        output_single_stem=None if keep_instrumental else "Vocals",
        use_autocast=precision != "fp32",
    )
    separator.load_model(model_filename=model_filename)
    produced = [Path(str(name)) for name in separator.separate(str(src))]
    paths = [p if p.is_absolute() else out_dir / p for p in produced]

    vocals = [p for p in paths if "vocals" in p.name.lower()]
    if not vocals:
        raise RuntimeError(f"抠人声没产出 vocals 轨，只有：{[p.name for p in paths]}")
    return vocals[0]


def make_analysis_copy(src: Path, dst: Path) -> None:
    """做 16 kHz 单声道副本，只喂给说话人分段，绝不用它导出成品。"""
    _ffmpeg(
        [
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(ANALYSIS_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


def diarize(wav: Path, device: str, max_speakers: int | None = None) -> Any:
    """切段认人。返回 pyannote 的 DiarizeOutput。

    自己把波形读进内存再喂进去，不给 pipeline 传文件路径。因为传路径会让 pyannote 走
    torchcodec 解码，而 torchcodec 在 Windows 上要求 FFmpeg 的动态库，本机只有静态版
    ffmpeg.exe，会直接报 libtorchcodec_core*.dll 加载失败。解码交给我们自己的 ffmpeg
    命令行，这个坑就不存在了。
    """
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=True)
    if pipeline is None:
        raise RuntimeError(
            f"{DIARIZATION_MODEL} 载入失败。多半是没在它网页上接受使用条款，"
            "或者令牌没有读受限仓库的权限"
        )
    pipeline.to(torch.device(device))

    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(samples).T  # pyannote 要 (声道, 采样点)
    audio = {"waveform": waveform, "sample_rate": int(sample_rate), "uri": wav.stem}

    with ProgressHook() as hook:
        return pipeline(audio, max_speakers=max_speakers, hook=hook)
