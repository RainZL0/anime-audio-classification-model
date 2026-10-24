"""Vocal processing at the original sample rate, and a 16 kHz copy used only for analysis."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soundfile as sf

SEPARATION_MODEL = "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt"
MODELS_DIR = Path("models")
"""Where the voice separation model is kept: `models` in the folder avoc was started in."""
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
PRECISIONS = {"fp32": "float32", "fp16": "float16", "bf16": "bfloat16"}
ANALYSIS_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class AudioInfo:
    """Basic parameters of one audio file."""

    sample_rate: int
    channels: int
    duration: float


def audio_info(path: Path) -> AudioInfo:
    """Read the sample rate, channel count and duration, without loading the audio into memory."""
    info = sf.info(str(path))
    return AudioInfo(
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        duration=float(info.frames) / float(info.samplerate),
    )


def _ffmpeg(args: list[str]) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("ffmpeg not found. Install it first and add it to PATH")
    proc = subprocess.run(
        [exe, "-v", "error", "-y", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[:500]}")


@dataclass(frozen=True)
class AudioTrack:
    """One audio track of a video file."""

    number: int
    """Its place among the audio tracks, from 0, as ffmpeg's `0:a:N` counts them."""
    tag: str
    """Its language tag as written in the file, such as `jpn`. Empty when there is none."""
    default: bool
    """Whether the file marks it as the track to play by default."""
    title: str = ""


def audio_tracks(video: Path) -> list[AudioTrack]:
    """The audio tracks of a video, read with ffprobe. Empty if it cannot be read."""
    import json

    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe not found. It is installed together with ffmpeg")
    proc = subprocess.run(
        [probe, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream_tags=language,title:stream_disposition=default", "-of", "json", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip
    try:
        streams = json.loads(proc.stdout or "{}").get("streams", [])
    except ValueError:
        return []
    return [
        AudioTrack(
            number=k,
            tag=str(s.get("tags", {}).get("language", "")),
            default=bool(s.get("disposition", {}).get("default")),
            title=str(s.get("tags", {}).get("title", "")),
        )
        for k, s in enumerate(streams)
    ]


def can_read(path: Path) -> bool:
    """Whether ffprobe can open the file as audio or video at all."""
    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe not found. It is installed together with ffmpeg")
    proc = subprocess.run([probe, "-v", "error", str(path)], capture_output=True, check=False)
    return proc.returncode == 0


def extract_audio(video: Path, dst: Path, track: int = 0) -> None:
    """Take one audio track (the first by default) out of the video and save it losslessly as
    FLAC. The sample rate and channels are not changed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-i", str(video), "-vn", "-map", f"0:a:{track}", "-c:a", "flac", str(dst)])


def download_separation_model(
    report: Callable[[str], None], models_dir: Path = MODELS_DIR, model: str = SEPARATION_MODEL
) -> None:
    """Download the voice separation model the first time, saying how big it is, with a progress
    bar on stderr (the add page shows it). audio-separator would download it by itself inside
    `separate_vocals`, but silently, and straight into the final file, so a download cut off
    halfway left a broken model behind. Here each file goes to a .part file first and is renamed
    when complete. Which files to fetch, and from where, is still audio-separator's choice."""
    if (models_dir / model).is_file():
        return
    import requests
    from audio_separator.separator import Separator
    from tqdm import tqdm

    from avoc.language import say

    class Reporting(Separator):
        def download_file_if_not_exists(self, url: str, output_path: str) -> None:
            target = Path(output_path)
            if target.is_file():
                return
            response = requests.get(url, stream=True, timeout=300)
            if response.status_code != 200:
                # audio-separator tries the next place on this error.
                raise RuntimeError(f"Failed to download {url}: {response.status_code}")
            size = int(response.headers.get("content-length", 0))
            if size >= 2**20:
                where = target.parent.resolve()
                report(
                    say(
                        f"第一次用：下载人声分离模型 {target.name}（{size / 2**20:.0f} MB），"
                        f"存到 {where}，以后不用再下",
                        f"First time: downloading the voice separation model {target.name} "
                        f"({size / 2**20:.0f} MB) to {where}; it is only downloaded once",
                    )
                )
            part = target.with_name(target.name + ".part")
            with (
                part.open("wb") as file,
                tqdm(
                    total=size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    disable=size < 2**20,
                ) as bar,
            ):
                for chunk in response.iter_content(chunk_size=1 << 16):
                    file.write(chunk)
                    bar.update(len(chunk))
            part.replace(target)

    models_dir.mkdir(parents=True, exist_ok=True)
    Reporting(log_level=logging.WARNING, model_file_dir=str(models_dir)).download_model_files(model)


def separate_vocals(
    src: Path,
    out_dir: Path,
    models_dir: Path,
    sample_rate: int,
    model_filename: str = SEPARATION_MODEL,
    keep_instrumental: bool = False,
    precision: str = "fp16",
) -> Path:
    """Voice separation. sample_rate must be the source file's sample rate, otherwise the library
    resamples to 44100 by default.

    precision is fp32, fp16 or bf16. The default is fp16. For the measurements behind this choice,
    see docs/TOOLS.md. Low precision is much faster, but its output differs slightly from full
    precision. When audio-separator calls autocast without a dtype, it uses torch's global default
    (fp16 on CUDA), so the only way to get bf16 is to change that default.
    """
    import torch
    from audio_separator.separator import Separator

    if precision not in PRECISIONS:
        raise ValueError(f"precision must be one of {', '.join(PRECISIONS)}, got {precision}")

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
        raise RuntimeError(
            f"Voice separation produced no vocals track. Only got: {[p.name for p in paths]}"
        )
    return vocals[0]


def make_analysis_copy(src: Path, dst: Path) -> None:
    """Make a 16 kHz mono copy. It is only fed to speaker segmentation and is never used to export
    the final output."""
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
    """Split audio into segments and identify the speakers. Returns pyannote's DiarizeOutput.

    The waveform is read into memory here and passed in, instead of giving the pipeline a file path.
    A file path makes pyannote decode through torchcodec, and on Windows torchcodec needs FFmpeg's
    shared libraries (DLLs). This machine only has the static build ffmpeg.exe, so loading fails
    with libtorchcodec_core*.dll errors. Decoding is done by our own ffmpeg command line instead, so
    this pitfall does not come up.
    """
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=True)
    if pipeline is None:
        raise RuntimeError(
            f"{DIARIZATION_MODEL} failed to load. Most likely you have not accepted "
            "its terms of use on its web page, "
            "or your token does not have permission to read gated repositories"
        )
    pipeline.to(torch.device(device))

    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(samples).T  # pyannote expects (channels, samples)
    audio = {"waveform": waveform, "sample_rate": int(sample_rate), "uri": wav.stem}

    with ProgressHook() as hook:
        return pipeline(audio, max_speakers=max_speakers, hook=hook)
