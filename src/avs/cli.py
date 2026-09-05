"""avs 命令行入口。各子命令对应管线的一个阶段，读写同一张 segments 表。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="avs",
    help="把一部动画拆成按人分好组的纯净人声片段。",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """anime-voice-sorter"""


@app.command()
def version() -> None:
    """打印版本号。"""
    from avs import __version__

    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """检查运行环境：CUDA、关键依赖是否可用。"""
    import torch

    typer.echo(f"torch           {torch.__version__}")
    typer.echo(f"cuda available  {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        typer.echo(f"device          {torch.cuda.get_device_name(0)}")
    for mod in ("torchaudio", "pyannote.audio", "audio_separator", "pysubs2", "soundfile"):
        try:
            __import__(mod)
            typer.echo(f"{mod:<15} ok")
        except Exception as exc:
            typer.echo(f"{mod:<15} FAILED: {exc}")


@app.command()
def probe(
    audio: Annotated[Path, typer.Argument(help="原始音轨，比如 data/raw/uma_s2_01.flac")],
    minutes: Annotated[float, typer.Option(help="只跑开头多少分钟，0 表示整集")] = 0.0,
    start: Annotated[float, typer.Option(help="从第几秒开始，配合 --minutes 用")] = 0.0,
    out: Annotated[Path, typer.Option(help="产物放哪")] = Path("runs/probe"),
    name: Annotated[str, typer.Option(help="这次测试叫什么，默认用文件名")] = "",
    clips: Annotated[int, typer.Option(help="每个说话人导出几条试听片段")] = 6,
    max_speakers: Annotated[int, typer.Option(help="说话人数上限，0 表示不限")] = 0,
    device: Annotated[str, typer.Option(help="cuda 或 cpu")] = "cuda",
    keep_instrumental: Annotated[bool, typer.Option(help="连伴奏轨一起存下来")] = False,
    skip_diarize: Annotated[bool, typer.Option(help="只做抠人声那一半")] = False,
    precision: Annotated[str, typer.Option(help="抠人声的推理精度：fp32 / fp16 / bf16")] = "fp16",
    keep_ratio: Annotated[float, typer.Option(help="音质筛选保留比例，越小越严")] = 0.5,
    vocals_in: Annotated[
        Path | None, typer.Option(help="复用已经抠好的人声轨，跳过抠人声这一步")
    ] = None,
) -> None:
    """摸底测试：抠人声 + 切段认人，量效果和耗时。"""
    from avs import probe as avs_probe

    if not audio.exists():
        typer.echo(f"找不到 {audio}")
        raise typer.Exit(1)

    run_dir = out / (name or audio.stem)
    run_dir.mkdir(parents=True, exist_ok=True)

    source = audio
    if minutes > 0 or start > 0:
        window = run_dir / f"window_{audio.stem}.flac"
        typer.echo(f"截取 {start:.0f} 秒起的 {minutes:.1f} 分钟 -> {window}")
        avs_probe.cut_window(audio, window, start, minutes)
        source = window

    info = avs_probe.audio_info(source)
    state = avs_probe.Probe(source=source, info=info)
    typer.echo(f"素材 {info.sample_rate} Hz / {info.channels} 声道 / {info.duration / 60:.1f} 分钟")

    if vocals_in is not None:
        vocals = vocals_in
        typer.echo(f"复用已有人声轨 {vocals}")
    else:
        typer.echo(f"抠人声（{avs_probe.SEPARATION_MODEL}，{precision}）……")
        with avs_probe.timed(state, "抠人声", info.duration):
            vocals = avs_probe.separate_vocals(
                src=source,
                out_dir=run_dir / "separated",
                models_dir=Path("models"),
                sample_rate=info.sample_rate,
                keep_instrumental=keep_instrumental,
                precision=precision,
            )
    state.artifacts["vocals"] = str(vocals)
    typer.echo(f"人声轨 -> {vocals}")

    if not skip_diarize:
        analysis = run_dir / "analysis_16k.wav"
        with avs_probe.timed(state, "做 16 kHz 分析副本"):
            avs_probe.make_analysis_copy(vocals, analysis)
        state.artifacts["analysis"] = str(analysis)

        typer.echo(f"切段认人（{avs_probe.DIARIZATION_MODEL}）……")
        with avs_probe.timed(state, "切段认人", info.duration):
            result = avs_probe.diarize(analysis, device, max_speakers or None)
        annotation = result.speaker_diarization

        rttm = run_dir / "diarization.rttm"
        with rttm.open("w", encoding="utf-8") as handle:
            annotation.write_rttm(handle)
        state.artifacts["rttm"] = str(rttm)

        state.stats = avs_probe.summarize(annotation, info.duration)

        from avs.stages.segment import build_segments

        with avs_probe.timed(state, "整理候选片段"):
            segments, build_info = build_segments(annotation, result.exclusive_speaker_diarization)
        state.stats["built"] = avs_probe.summarize_built(segments, build_info)
        segments_file = run_dir / "segments.json"
        segments_file.write_text(
            json.dumps(
                [{"speaker": s.speaker, "start": s.start, "end": s.end} for s in segments],
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        state.artifacts["segments"] = str(segments_file)
        counts = build_info["counts"]
        typer.echo(
            f"候选片段 {counts['raw']} 段 -> 整理后留下 {counts['kept']} 段"
            f"（共 {counts['kept_sec']} 秒），疑似唱歌 {counts['suspected_song']} 段"
        )

        from avs.stages.quality import keep_best, score_segments
        from avs.stages.quality import summarize as summarize_quality

        typer.echo("按音质打分并筛选……")
        with avs_probe.timed(state, "音质打分"):
            scored = score_segments(analysis, segments, device=device)
        kept, rejected = keep_best(scored, keep_ratio=keep_ratio)
        state.stats["quality"] = summarize_quality(kept, rejected)
        (run_dir / "quality.json").write_text(
            json.dumps([q.__dict__ for q in scored], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        typer.echo(
            f"音质筛选：留下 {len(kept)} 条（共 {state.stats['quality']['kept_sec']} 秒），"
            f"淘汰 {len(rejected)} 条"
        )

        with avs_probe.timed(state, "切试听片段"):
            written = avs_probe.export_clips(kept, vocals, run_dir / "clips", clips)
        typer.echo(f"试听片段 {written} 条 -> {run_dir / 'clips'}")

    report = avs_probe.write_report(state, run_dir)
    typer.echo(f"\n小结 -> {report}")
