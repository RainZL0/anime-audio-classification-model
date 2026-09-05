"""avs 命令行入口。各子命令对应管线的一个阶段，读写同一张 segments 表。"""

from __future__ import annotations

import contextlib
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


ANNOTATIONS = Path("annotations")
"""人工标注归档在这。`runs/` 被 git 忽略，而人工标注不可再生，所以单独放一份。"""


def _source_of(run_dir: Path) -> str:
    """这次测试用的是哪个音轨。人声轨的路径里带着它，够归档用了。"""
    stats_file = run_dir / "stats.json"
    if not stats_file.exists():
        return str(run_dir)
    artifacts = json.loads(stats_file.read_text(encoding="utf-8"))["artifacts"]
    return str(artifacts.get("vocals", run_dir))


def _vocals_of(run_dir: Path) -> Path:
    stats_file = run_dir / "stats.json"
    if not stats_file.exists():
        typer.echo(f"找不到 {stats_file}，先跑一次 avs probe")
        raise typer.Exit(1)
    vocals = Path(json.loads(stats_file.read_text(encoding="utf-8"))["artifacts"]["vocals"])
    if not vocals.exists():
        typer.echo(f"找不到人声轨 {vocals}")
        raise typer.Exit(1)
    return vocals


@app.command()
def label(
    run_dir: Annotated[Path, typer.Argument(help="probe 跑出来的目录，比如 runs/probe/ep01_v4")],
    mode: Annotated[
        str, typer.Option(help="names 对着画面报名字（推荐），pairs 两两比对，groups 听音分组")
    ] = "names",
    model: Annotated[str, typer.Option(help="pairs 模式按哪个模型的距离分档")] = "redimnet2-b6",
    per_bin: Annotated[int, typer.Option(help="pairs 模式每档抽几对")] = 6,
    per_speaker: Annotated[int, typer.Option(help="groups 模式每个机器分组抽几条")] = 5,
    keep_ratio: Annotated[float, typer.Option(help="groups 模式只从音质最好的这个比例里抽")] = 0.5,
    port: Annotated[int, typer.Option(help="本地服务用哪个端口")] = 8765,
) -> None:
    """人工标注，用来破掉循环论证。只听 127.0.0.1，音频不出本机。

    三种模式，都看不到机器的答案。**推荐 names**，因为它的真答案来自视频而不是耳朵：

    - **names（默认）**：给出时间点，你在动画里跳到那儿看是谁在说，把名字打进去。
      片段按时间排好，视频从头拖一遍就行。这是唯一能给出「真的是谁」的模式，
      标出来的东西还能当第 4 阶段的评估集用。
    - **pairs**：一次放两条，问是不是同一个人。不需要视频，答完就忘。
      配对按声纹距离分档抽，能直接量出分界线该定在哪。
    - **groups**：听一条丢进一组。要在脑子里同时记住好几个人，一集有 9 个说话人时
      基本记不住，实测一半的片段会被标成「听不清」。留着备用，不推荐。

    进度随时存盘，下次再跑接着上次的。
    """
    from avs.stages.label import export_sample, load_sample, pick_sample, save_sample
    from avs.stages.label_server import serve, write_page

    if mode == "pairs":
        return _label_pairs(run_dir, model, per_bin, port)
    if mode == "names":
        return _label_names(run_dir, per_speaker, keep_ratio, port)
    if mode != "groups":
        typer.echo(f"mode 只能是 names、pairs 或 groups，收到 {mode!r}")
        raise typer.Exit(1)

    quality_file = run_dir / "quality.json"
    if not quality_file.exists():
        typer.echo(f"找不到 {quality_file}，先跑一次 avs probe")
        raise typer.Exit(1)
    vocals = _vocals_of(run_dir)

    clip_dir = run_dir / "label_clips"
    sample_file = run_dir / "label_sample.json"
    labels_file = run_dir / "labels.json"

    if sample_file.exists():
        sample = load_sample(sample_file)
        typer.echo(f"接着上次的抽样，{len(sample.clips)} 条")
    else:
        scored = json.loads(quality_file.read_text(encoding="utf-8"))
        scored.sort(key=lambda q: q["score"], reverse=True)
        kept = scored[: max(1, round(len(scored) * keep_ratio))]
        sample = pick_sample(kept, per_speaker=per_speaker)
        save_sample(sample, sample_file)
        typer.echo(f"从音质最好的 {len(kept)} 条里抽了 {len(sample.clips)} 条来标")
        typer.echo(f"切片段到 {clip_dir} ……")
        export_sample(sample, vocals, clip_dir)

    labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}
    write_page(clip_dir, sample, labels)

    typer.echo(f"\n已标 {len(labels)} / {len(sample.clips)} 条")
    typer.echo(f"打开 http://127.0.0.1:{port}/ 开始标，标完按 Ctrl+C 停掉服务")
    try:
        serve(clip_dir, labels_file, port)
    except KeyboardInterrupt:
        typer.echo(f"\n停了。结果在 {labels_file}")
    return None


def _label_names(run_dir: Path, per_speaker: int, keep_ratio: float, port: int) -> None:
    """对着画面报名字。真答案来自视频，不靠耳朵，所以标出来的东西最可信。"""
    from avs.stages.label import (
        by_time,
        export_annotation,
        export_sample,
        load_sample,
        pick_sample,
        save_sample,
    )
    from avs.stages.label_server import serve, write_names_page

    quality_file = run_dir / "quality.json"
    if not quality_file.exists():
        typer.echo(f"找不到 {quality_file}，先跑一次 avs probe")
        raise typer.Exit(1)
    vocals = _vocals_of(run_dir)

    clip_dir = run_dir / "label_clips"
    sample_file = run_dir / "label_sample.json"
    names_file = run_dir / "names.json"

    if sample_file.exists():
        sample = load_sample(sample_file)
        typer.echo(f"用已有的抽样，{len(sample.clips)} 条")
    else:
        scored = json.loads(quality_file.read_text(encoding="utf-8"))
        scored.sort(key=lambda q: q["score"], reverse=True)
        kept = scored[: max(1, round(len(scored) * keep_ratio))]
        sample = pick_sample(kept, per_speaker=per_speaker)
        save_sample(sample, sample_file)
        typer.echo(f"从音质最好的 {len(kept)} 条里抽了 {len(sample.clips)} 条")
        typer.echo(f"切片段到 {clip_dir} ……")
        export_sample(sample, vocals, clip_dir)

    clips = by_time(sample)
    names = json.loads(names_file.read_text(encoding="utf-8")) if names_file.exists() else {}
    write_names_page(clip_dir, clips, names)

    typer.echo(
        f"\n已标 {len(names)} / {len(clips)} 条，时间点从 {clips[0]['stamp']} "
        f"到 {clips[-1]['stamp']}"
    )
    typer.echo("时间戳是相对这一集音轨开头的，跟视频应该对得上，第一条先核对一下")
    typer.echo(f"打开 http://127.0.0.1:{port}/ 开始标，标完按 Ctrl+C 停掉服务")
    with contextlib.suppress(KeyboardInterrupt):
        serve(clip_dir, names_file, port)

    # runs/ 是被 git 忽略的，人工标注不可再生，所以停下来时归档一份到会被跟踪的地方
    names = json.loads(names_file.read_text(encoding="utf-8")) if names_file.exists() else {}
    ear_file = run_dir / "labels_groups.json"
    archive = ANNOTATIONS / f"{run_dir.name}.json"
    export_annotation(
        archive,
        sample,
        names,
        source=str(_source_of(run_dir)),
        run=str(run_dir),
        by_ear=json.loads(ear_file.read_text(encoding="utf-8")) if ear_file.exists() else None,
    )
    typer.echo(f"\n停了。标了 {len(names)} 条，归档到 {archive}（这份会进 git）")
    return None


def _label_pairs(run_dir: Path, model: str, per_bin: int, port: int) -> None:
    """两两比对模式。要先跑过 avs embed，因为配对是按声纹距离分档抽的。"""
    import numpy as np

    from avs.embeddings.extract import Embedded
    from avs.stages.label import (
        export_sample,
        load_pairs,
        load_sample,
        pairs_report,
        pick_pairs,
        save_pairs,
        save_sample,
    )
    from avs.stages.label_server import serve, write_pairs_page

    vectors_file = run_dir / f"embeddings_{model}.npy"
    meta_file = run_dir / f"embeddings_{model}.json"
    if not (vectors_file.exists() and meta_file.exists()):
        typer.echo(f"找不到 {model} 的指纹，先跑 avs embed {run_dir}")
        raise typer.Exit(1)
    vocals = _vocals_of(run_dir)

    clip_dir = run_dir / "pair_clips"
    sample_file = run_dir / "pair_sample.json"
    pairs_file = run_dir / "pairs.json"
    answers_file = run_dir / "pair_answers.json"

    if pairs_file.exists() and sample_file.exists():
        pairs = load_pairs(pairs_file)
        sample = load_sample(sample_file)
        typer.echo(f"接着上次的题目，{len(pairs)} 题")
    else:
        meta = [Embedded(**item) for item in json.loads(meta_file.read_text(encoding="utf-8"))]
        sample, pairs = pick_pairs(meta, np.load(vectors_file), per_bin=per_bin)
        save_sample(sample, sample_file)
        save_pairs(pairs, pairs_file)
        typer.echo(f"出了 {len(pairs)} 道题，涉及 {len(sample.clips)} 条片段")
        typer.echo(f"切片段到 {clip_dir} ……")
        export_sample(sample, vocals, clip_dir)

    answers = json.loads(answers_file.read_text(encoding="utf-8")) if answers_file.exists() else {}
    write_pairs_page(clip_dir, pairs, answers)

    typer.echo(f"\n已答 {len(answers)} / {len(pairs)} 题")
    typer.echo(f"打开 http://127.0.0.1:{port}/ 开始答，答完按 Ctrl+C 出结果")
    with contextlib.suppress(KeyboardInterrupt):
        serve(clip_dir, answers_file, port)

    answers = json.loads(answers_file.read_text(encoding="utf-8")) if answers_file.exists() else {}
    report = pairs_report(pairs, answers)
    (run_dir / "pairs_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    typer.echo(f"\n答了 {report['answered']} 题，拿不准 {report['unsure']} 题")
    typer.echo("  声纹距离          听着是同一个人")
    for row in report["curve"]:
        bar = "█" * round(row["rate"] * 20)
        typer.echo(
            f"  {row['distance_from']:.3f}-{row['distance_to']:.3f}"
            f"  {row['said_same']}/{row['answered']}  {bar}"
        )
    if report["threshold"] is not None:
        typer.echo(f"\n分界线大约在 {report['threshold']}（人耳判同的比例穿过 50% 的地方）")
    else:
        typer.echo("\n还读不出分界线，可能是答的题太少，或者曲线没穿过 50%")
    typer.echo(f"跟机器的看法一致的比例 {report['agrees_with_machine']}")


@app.command()
def embed(
    run_dir: Annotated[Path, typer.Argument(help="probe 跑出来的目录，比如 runs/probe/ep01_v4")],
    model: Annotated[
        str, typer.Option(help="指纹模型：redimnet2-b6 / wespeaker-resnet293 / all")
    ] = "all",
    keep_ratio: Annotated[
        float, typer.Option(help="只用音质最好的这个比例，跟 probe 保持一致")
    ] = 0.5,
    device: Annotated[str, typer.Option(help="cuda 或 cpu")] = "cuda",
) -> None:
    """算声音指纹，并量一次「声纹距离能不能把人分开」。

    读 probe 留下的 quality.json 和 analysis_16k.wav，不重跑前面的步骤。
    两个模型都跑一遍再比，理由见 TOOLS.md 第 2 节。
    """
    from avs.embeddings.extract import MODELS, embed_segments
    from avs.evaluation.distance import distance_report, format_report
    from avs.stages.label import apply_labels, load_annotation, load_sample, purity

    quality_file = run_dir / "quality.json"
    analysis = run_dir / "analysis_16k.wav"
    for path in (quality_file, analysis):
        if not path.exists():
            typer.echo(f"找不到 {path}，先跑一次 avs probe")
            raise typer.Exit(1)

    scored = json.loads(quality_file.read_text(encoding="utf-8"))
    scored.sort(key=lambda q: q["score"], reverse=True)
    kept = scored[: max(1, round(len(scored) * keep_ratio))]
    typer.echo(f"用音质最好的 {len(kept)} 条（共 {len(scored)} 条打过分）")

    # 标注做过了就顺便拿人工标签再算一遍，那份才不是自己证明自己。
    # 优先读 annotations/ 里的归档，它是会进 git 的那一份。
    sample_file = run_dir / "label_sample.json"
    archive = ANNOTATIONS / f"{run_dir.name}.json"
    human = None
    if archive.exists():
        human = (archive, *load_annotation(archive))
        typer.echo(f"找到人工标注 {len(human[2])} 条（看画面标的，来自 {archive}），会一并算")
    elif (run_dir / "names.json").exists() and sample_file.exists():
        source = run_dir / "names.json"
        human = (source, load_sample(sample_file), json.loads(source.read_text("utf-8")))
        typer.echo(f"找到人工标注 {len(human[2])} 条（{source} 还没归档，先用着）")

    wanted = list(MODELS) if model == "all" else [model]
    for name in wanted:
        typer.echo(f"\n算指纹（{name}）……")
        meta, vectors = embed_segments(analysis, kept, model=name, device=device)

        import numpy as np

        np.save(run_dir / f"embeddings_{name}.npy", vectors)
        (run_dir / f"embeddings_{name}.json").write_text(
            json.dumps([m.__dict__ for m in meta], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

        report = distance_report(meta, vectors)
        # 文件名里不带比例，换个比例会覆盖上一次，所以把比例记进结果里
        report["keep_ratio"] = keep_ratio
        (run_dir / f"distance_{name}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        typer.echo(format_report(name, report))

        if human is None:
            continue
        _, sample, labels = human
        human_meta, book = apply_labels(meta, labels, sample)
        if len(human_meta) < 4:
            typer.echo("  人工标注太少，先去 avs label 多标几条")
            continue
        human_report = distance_report(human_meta, vectors[book["indices"]])
        human_report["keep_ratio"] = keep_ratio
        human_report["labelled_by"] = "人工"
        human_report["skipped"] = book["skipped"]
        (run_dir / f"distance_{name}_human.json").write_text(
            json.dumps(human_report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        typer.echo(format_report(f"{name}（人工标注）", human_report))

    if human is None:
        typer.echo(
            "\n提醒：这里的「同一个人」是切段认人给的标签，不是人工标注。"
            "结果差是硬结论，结果好还得人工听过才算数。"
            "\n跑 avs label 标几十条，就能拿人工标签再算一遍。"
        )
        return

    scores = purity(human[1], human[2])
    (run_dir / "purity.json").write_text(
        json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    typer.echo(f"\n机器分组的纯度（按人工标注算）：整体 {scores['overall_purity']}")
    for machine, row in scores["groups"].items():
        extra = "，".join(f"{k} {v} 条" for k, v in row["special"].items())
        typer.echo(
            f"  {machine}  标了 {row['labeled']} 条，纯度 {row['purity']}"
            + (f"（{extra}）" if extra else "")
        )
    typer.echo("  只有一条的组纯度必然是 1.0，别当证据。")


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
