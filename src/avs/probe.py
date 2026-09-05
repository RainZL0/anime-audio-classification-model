"""摸底测试：在真实动画音轨上量一遍「抠人声 + 切段认人」的效果和开销。

这不是管线的一步，是 STATUS.md 里那个「先测后写」的小测试，用来决定后面每个阶段
各投多少精力。它只读原始音轨，所有产物写进 runs/probe/<名字>/，不碰 data/。

刻意遵守的一条规矩：抠人声在**原始采样率**上做，16 kHz 单声道副本只喂给说话人分段，
试听片段一律从原始采样率的人声轨上切。理由见 HOW_IT_WORKS.md 的「一条绝对不能犯的错」。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import soundfile as sf

# 见 TOOLS.md 第 2 节。文档里写的 kimmel_unwa_ft2_bleedless 在 audio-separator 的
# 模型表里叫这个名字。
SEPARATION_MODEL = "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

# 抠人声可选的推理精度，值是 torch 里的 dtype 名字（torch 延迟到用时才 import）
PRECISIONS = {"fp32": "float32", "fp16": "float16", "bf16": "bfloat16"}

ANALYSIS_SAMPLE_RATE = 16_000
# 导出成品能用的时长区间，见 HOW_IT_WORKS.md 4.7
USABLE_MIN_SEC = 1.0
USABLE_MAX_SEC = 12.0


@dataclass(frozen=True)
class AudioInfo:
    """一个音频文件的基本参数。"""

    sample_rate: int
    channels: int
    duration: float


@dataclass
class Step:
    """一个步骤花了多久。realtime 是「音频时长 ÷ 耗时」，大于 1 表示比实时快。"""

    name: str
    seconds: float
    realtime: float | None = None


@dataclass
class Probe:
    """一次摸底测试的全部结果。"""

    source: Path
    info: AudioInfo
    steps: list[Step] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


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


@contextmanager
def timed(probe: Probe, name: str, audio_seconds: float | None = None) -> Iterator[None]:
    """记一个步骤的耗时。audio_seconds 给了就顺便算相对实时的倍率。"""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    realtime = (audio_seconds / elapsed) if audio_seconds and elapsed > 0 else None
    probe.steps.append(Step(name=name, seconds=elapsed, realtime=realtime))


def cut_window(src: Path, dst: Path, start_sec: float, minutes: float) -> None:
    """截一段出来试跑，采样率和声道数原样保留。minutes <= 0 表示要整集。"""
    args = ["-ss", f"{start_sec:.3f}", "-i", str(src)]
    if minutes > 0:
        args += ["-t", f"{minutes * 60:.3f}"]
    args += ["-vn", "-c:a", "flac", "-compression_level", "5", str(dst)]
    _ffmpeg(args)


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

    precision 取 fp32 / fp16 / bf16，默认 fp16，理由见决策 13。低精度快得多，代价是
    输出和全精度有细微出入，实测数字见 STATUS.md。audio-separator 调 autocast 时不指定 dtype，等于用
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


def summarize(annotation: Any, total_duration: float) -> dict[str, Any]:
    """把分段结果压成几个能一眼看懂的数字。"""
    speech = float(annotation.get_timeline().support().duration())
    overlap = float(annotation.get_overlap().duration())

    durations: list[float] = []
    speakers: list[dict[str, Any]] = []
    for label in annotation.labels():
        segs = sorted(float(s.duration) for s in annotation.label_timeline(label))
        durations += segs
        speakers.append(
            {
                "speaker": str(label),
                "segments": len(segs),
                "total_sec": round(sum(segs), 1),
                "median_sec": round(segs[len(segs) // 2], 2) if segs else 0.0,
            }
        )
    speakers.sort(key=lambda row: float(row["total_sec"]), reverse=True)

    usable = [d for d in durations if USABLE_MIN_SEC <= d <= USABLE_MAX_SEC]
    return {
        "num_speakers": len(speakers),
        "total_sec": round(total_duration, 1),
        "speech_sec": round(speech, 1),
        "speech_ratio": round(speech / total_duration, 3) if total_duration else 0.0,
        "overlap_sec": round(overlap, 1),
        "overlap_ratio_of_speech": round(overlap / speech, 3) if speech else 0.0,
        "num_segments": len(durations),
        "usable_segments": len(usable),
        "usable_sec": round(sum(usable), 1),
        "speakers": speakers,
    }


def summarize_built(segments: list[Any], build_info: dict[str, Any]) -> dict[str, Any]:
    """整理之后剩下什么，以及每个说话人还剩多少料。"""
    from collections import defaultdict

    from avs.stages.segment import adjacency_rate

    by_speaker: dict[str, list[float]] = defaultdict(list)
    for seg in segments:
        by_speaker[seg.speaker].append(seg.duration)

    speakers: list[dict[str, Any]] = [
        {
            "speaker": name,
            "segments": len(durations),
            "total_sec": round(sum(durations), 1),
            "median_sec": round(sorted(durations)[len(durations) // 2], 2),
        }
        for name, durations in by_speaker.items()
    ]
    speakers.sort(key=lambda row: float(row["total_sec"]), reverse=True)

    return {
        "counts": build_info["counts"],
        "adjacency_rate": round(adjacency_rate(segments), 3),
        "num_speakers": len(speakers),
        "speakers": speakers,
        "songs": build_info["songs"],
    }


def _pick_samples(segments: list[Any], count: int) -> list[Any]:
    """挑试听片段：沿时间轴均匀取，别全挑同一场戏的。时长已经在建片段时筛过了。"""
    ordered = sorted(segments, key=lambda s: s.start)
    if len(ordered) <= count:
        return ordered
    stride = len(ordered) / count
    return [ordered[int(i * stride)] for i in range(count)]


def export_clips(segments: list[Any], vocals: Path, out_dir: Path, per_speaker: int) -> int:
    """从原始采样率的人声轨上切试听片段，一个说话人一个目录。"""
    from collections import defaultdict

    by_speaker: dict[str, list[Any]] = defaultdict(list)
    for seg in segments:
        by_speaker[seg.speaker].append(seg)

    info = audio_info(vocals)
    written = 0
    for speaker, own in by_speaker.items():
        picked = _pick_samples(own, per_speaker)
        if not picked:
            continue
        speaker_dir = out_dir / speaker.lower()
        speaker_dir.mkdir(parents=True, exist_ok=True)
        for seg in picked:
            data, _ = sf.read(
                str(vocals),
                start=int(seg.start * info.sample_rate),
                stop=int(seg.end * info.sample_rate),
                always_2d=True,
            )
            stamp = f"{seg.start:07.2f}-{seg.end:07.2f}".replace(".", "p")
            sf.write(str(speaker_dir / f"{stamp}.flac"), data, info.sample_rate)
            written += 1
    return written


def write_report(probe: Probe, out_dir: Path) -> Path:
    """写一份人能读的小结，外加一份机器能读的 json。"""
    (out_dir / "stats.json").write_text(
        json.dumps(
            {
                "source": str(probe.source),
                "info": probe.info.__dict__,
                "steps": [s.__dict__ for s in probe.steps],
                "stats": probe.stats,
                "artifacts": probe.artifacts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# 摸底测试结果",
        "",
        f"素材：`{probe.source.name}`　{probe.info.sample_rate} Hz　"
        f"{probe.info.channels} 声道　{probe.info.duration / 60:.1f} 分钟",
        "",
        "## 耗时",
        "",
        "| 步骤 | 耗时 | 相对实时 |",
        "| --- | --- | --- |",
    ]
    for step in probe.steps:
        speed = f"{step.realtime:.1f} 倍" if step.realtime else "—"
        lines.append(f"| {step.name} | {step.seconds:.1f} 秒 | {speed} |")

    stats = probe.stats
    if stats:
        lines += [
            "",
            "## 分段结果",
            "",
            f"- 认出 **{stats['num_speakers']}** 个说话人",
            f"- 有人说话的时间 {stats['speech_sec']} 秒，占全片 {stats['speech_ratio']:.0%}",
            f"- 两人重叠 {stats['overlap_sec']} 秒，占说话时间 "
            f"{stats['overlap_ratio_of_speech']:.1%}",
            f"- 切出 {stats['num_segments']} 段，其中 {stats['usable_segments']} 段落在 "
            f"{USABLE_MIN_SEC:.0f} 到 {USABLE_MAX_SEC:.0f} 秒的可用区间，"
            f"共 {stats['usable_sec']} 秒",
            "",
            "| 说话人 | 段数 | 总时长（秒） | 单段中位数（秒） |",
            "| --- | --- | --- | --- |",
        ]
        for row in stats["speakers"]:
            lines.append(
                f"| {row['speaker']} | {row['segments']} | "
                f"{row['total_sec']} | {row['median_sec']} |"
            )
    built = probe.stats.get("built")
    if built:
        counts = built["counts"]
        lines += [
            "",
            "## 整理之后的候选片段",
            "",
            "上面是模型的原始输出，直接拿去切会把邻座的声音带进来。这一节是",
            "`stages/segment.py` 整理之后的结果，`clips/` 里的片段来自这一步。",
            "",
            "| 处理 | 段数 |",
            "| --- | --- |",
            f"| 排他标注的原始段 | {counts['raw']} |",
            f"| 减掉重叠区间后 | {counts['after_overlap_removal']} |",
            f"| 合并同一人的相邻碎段后 | {counts['after_merge']} |",
            f"| 其中边界向内让过步的 | {counts['trimmed']} |",
            f"| 淘汰：太短 | {counts['dropped_too_short']} |",
            f"| 淘汰：太长 | {counts['dropped_too_long']} |",
            f"| 判为疑似唱歌 | {counts['suspected_song']}（共 {counts['song_sec']} 秒） |",
            f"| **最终留下** | **{counts['kept']}（共 {counts['kept_sec']} 秒）** |",
            "",
            f"「紧邻换人」的比例从原始输出降到 **{built['adjacency_rate']:.0%}**。"
            "这个数字直接对应串音风险，越低越好。",
            "",
            "| 说话人 | 段数 | 总时长（秒） | 单段中位数（秒） |",
            "| --- | --- | --- | --- |",
        ]
        for row in built["speakers"]:
            lines.append(
                f"| {row['speaker']} | {row['segments']} | "
                f"{row['total_sec']} | {row['median_sec']} |"
            )

    if stats:
        lines += [
            "",
            "## 接下来该由你判断",
            "",
            "听 `clips/` 里每个说话人目录下的片段，回答两件事：",
            "",
            "1. **一条片段里是不是只有一个人在说话**（这是这一轮要验的重点）",
            "2. **同一个目录里是不是同一个人**（这是各组纯度，靠分组解决，不是这一轮）",
            "",
            "两件事失败在不同环节，分开报，才知道下一步该修哪里。",
        ]

    report = out_dir / "REPORT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
