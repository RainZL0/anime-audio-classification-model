"""字幕说话人分类的唯一命令入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from avs import pipeline
from avs.project import write_json

app = typer.Typer(name="avs", help="按字幕切段，把同一角色的声音归到一起。", no_args_is_help=True)


@app.callback()
def main() -> None:
    # Windows 管道默认编码不一定能表示中文。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@app.command()
def doctor() -> None:
    """检查显卡与音频运行环境。"""
    import shutil

    import torch

    typer.echo(f"torch {torch.__version__}; CUDA {torch.cuda.is_available()}")
    typer.echo(f"ffmpeg: {shutil.which('ffmpeg') or '未安装'}")


@app.command()
def prepare(
    audio: Annotated[Path, typer.Argument(help="原始音轨")],
    subs: Annotated[Path, typer.Option(help="对应的对白字幕")],
    out: Annotated[Path, typer.Option(help="新的一集目录")],
    name: Annotated[str, typer.Option(help="唯一集名，例如 ep03")],
    vocals: Annotated[Path | None, typer.Option(help="复用已有的原采样率人声轨")] = None,
    offset: Annotated[float | None, typer.Option(help="字幕加上的秒数，省略则自动对齐")] = None,
    device: str = "cuda",
) -> None:
    """准备一集：抠人声、对齐字幕，每行对白一个片段。"""
    typer.echo(pipeline.prepare(audio, subs, out, name, vocals, offset, device))


@app.command()
def extend(
    episode: Path,
    subtitle: Annotated[Path, typer.Option(help="这一集的 ASS 字幕")],
    floor: Annotated[float, typer.Option(help="短于这个秒数的行不补，算不出可靠声纹")] = 0.2,
) -> None:
    """把字幕里没有对应片段的对白行补进片段表；已有片段不动，标签不用重做。"""
    result = pipeline.extend_segments(episode, subtitle, floor)
    typer.echo(
        f"{result['episode']}：{result['before']} 条 -> {result['after']} 条，"
        f"补了 {result['added']} 条（最短 {result['shortest_added']} 秒），"
        f"另有 {result['too_short']} 条短于 {result['floor_seconds']} 秒没补"
    )
    typer.echo("片段表变了，声纹缓存已失效，重新运行 embed")


@app.command()
def embed(
    episodes: Annotated[list[Path], typer.Argument(help="一集或多集目录")],
    model: str = "redimnet2-b6",
    device: str = "cuda",
    window: Annotated[
        float, typer.Option(help="最小听音窗口秒数；短片段向两侧借相邻音频补足，0 表示不补")
    ] = 0.0,
) -> None:
    """计算全量片段声纹，输入未变时复用缓存。"""
    for episode in episodes:
        typer.echo(pipeline.embed(episode, model, device, window))


@app.command()
def group(
    episodes: Annotated[list[Path], typer.Argument(help="要一起分组的集目录")],
    out: Annotated[Path, typer.Option(help="新的分组 JSON 文件")],
    threshold: Annotated[
        float | None, typer.Option(help="距离阈值；省略则用该模型自己的默认值")
    ] = None,
    model: str = "anime-va",
    method: Annotated[
        str, typer.Option(help="连接规则：average/single/complete/mutual_knn/two_stage")
    ] = "average",
    relative: Annotated[
        bool,
        typer.Option("--relative", help="分界线按这个池子自己的距离算，不用固定值；尚未独立检验"),
    ] = False,
) -> None:
    """只读取缓存进行全局分组，小组保留；可以反复调整阈值和连接规则。"""
    from avs.embeddings.extract import DEFAULT_THRESHOLDS

    if relative:
        if threshold is not None:
            raise typer.BadParameter("--relative 自己算分界线，不能同时给 --threshold")
        threshold = pipeline.relative_threshold(episodes, model)
        typer.echo(f"按池子算出的分界线 {threshold:.4f}（固定值是 {DEFAULT_THRESHOLDS[model]}）")
    elif threshold is None:
        threshold = DEFAULT_THRESHOLDS.get(model, 0.5)
        typer.echo(f"未指定阈值，用 {model} 的默认值 {threshold}")
    result = pipeline.group(episodes, out, threshold, model, method)
    typer.echo(result["summary"])
    typer.echo(f"分组 -> {out}")


@app.command()
def evaluate(
    groups: Path,
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Path = Path("runs/evaluation.json"),
) -> None:
    """精确对照人工身份，统计错误合并与该合没合。"""
    from avs.evaluation.identity import evaluate as score

    result = score(groups, annotation)
    write_json(out, result)
    typer.echo(result["metrics"])
    typer.echo(f"报告 -> {out}")


@app.command()
def compare(
    episodes: Annotated[list[Path], typer.Argument(help="固定的集目录")],
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的比较报告 JSON")],
    model: Annotated[list[str] | None, typer.Option(help="只比较这些模型，默认两个都比")] = None,
    method: Annotated[list[str] | None, typer.Option(help="连接规则，可重复；默认 average")] = None,
    low: Annotated[float, typer.Option(help="阈值扫描下界")] = 0.20,
    high: Annotated[float, typer.Option(help="阈值扫描上界")] = 0.90,
) -> None:
    """比较缓存模型与连接规则在给定阈值区间上的错误合并与该合没合；仅用于探索。

    默认区间是给 ReDimNet 定的。不同模型的相似度尺度不一样，换模型要先看同一角色的距离落在哪，
    再定区间；照搬别人的区间会扫在完全没有意义的一段上。
    """
    from avs.embeddings.extract import MODELS
    from avs.evaluation.compare import compare as compare_models

    if not 0 < low < high <= 2:
        raise typer.BadParameter("阈值区间必须满足 0 < low < high <= 2")
    grid = [i / 100 for i in range(round(low * 100), round(high * 100) + 1)]
    result = compare_models(episodes, annotation, model or list(MODELS), grid, out, method)
    typer.echo(f"比较 {len(result['results'])} 个设置 -> {out}")


@app.command()
def drift(
    episodes: Annotated[list[Path], typer.Argument(help="固定的集目录")],
    scored: Annotated[str, typer.Option(help="被打分的那一集集名，它始终整集在池子里")],
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的漂移报告 JSON")],
    model: str = "anime-va",
    threshold: Annotated[
        float | None, typer.Option(help="要考察的固定分界线，省略用模型默认值")
    ] = None,
    multiplier: Annotated[
        float | None, typer.Option(help="按池子定分界线时乘的倍数，省略用模型默认值")
    ] = None,
    steps: Annotated[int, typer.Option(help="池子大小取几档")] = 7,
    seeds: Annotated[int, typer.Option(help="每档抽几遍别的集的片段")] = 8,
) -> None:
    """量成绩随片段池变大怎么变，对比固定分界线和按池子定分界线两种做法。

    被打分的那一集始终整集在池子里，只往里加别的集的片段。每一档面对同一批标签、同一批配对，
    所以成绩可以直接比。要看的是错误合并稳不稳，不是连上多少对。
    """
    from avs.evaluation.drift import drift as run_drift

    report = run_drift(
        episodes, scored, annotation, out, model, threshold, multiplier, steps=steps, seeds=seeds
    )
    typer.echo(f"{report['labeled_clips']} 条标签、{report['roles']} 个角色，打分只看 {scored}")
    typer.echo("每行是一档池子，两种定分界线的做法并排；要看的是错误合并稳不稳")
    for row in report["summary"]:
        typer.echo(
            f"片段池 {row['pool_clips']:>5} 条："
            f"固定 {row['fixed_threshold']:.3f} 连上 {row['fixed_correct_pairs']:.0f}"
            f" 错误合并 {row['fixed_false_merges']:.0f}"
            f"；按池子定 {row['relative_threshold']:.4f}"
            f" 连上 {row['relative_correct_pairs']:.0f}"
            f" 错误合并 {row['relative_false_merges']:.0f}"
        )
    typer.echo(f"报告 -> {out}")


@app.command("classify-check")
def classify_check(
    episodes: Annotated[list[Path], typer.Argument(help="训练集和被测集的集目录")],
    test: Annotated[str, typer.Option(help="被测的那一集集名，它的标签不进训练")],
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的检验报告 JSON")],
    model: Annotated[
        list[str] | None, typer.Option(help="声纹模型，可重复提供；多个时拼在一起")
    ] = None,
) -> None:
    """按集留出检验：在别的集的标签上训练，把被测集的片段直接分到角色名下。"""
    from avs.evaluation.classify import classify_check as run_check

    report = run_check(episodes, test, annotation, out, model or ["anime-va"])
    typer.echo(
        f"{'+'.join(report['models'])}：训练 {sum(report['train_episodes'].values())} 条，"
        f"测 {report['test_clips']} 条，其中 {report['unseen_role_clips']} 条的角色训练集里没有"
    )
    for method, own in report["results"].items():
        tiers = "，".join(
            f"{k} {v['accuracy']}（{v['clips']} 条）" for k, v in own["by_duration"].items()
        )
        confident = "，".join(f"{k} {v}" for k, v in own["by_confidence"].items())
        typer.echo(f"{method}：全部 {own['accuracy']}；按把握 {confident}")
        typer.echo(f"  按时长 {tiers}")
    typer.echo(f"报告 -> {out}")


@app.command()
def references(
    groups: Path,
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    role: Annotated[list[str], typer.Option(help="要试验参考合组的角色名，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的实验输出目录")],
    nearest: Annotated[bool, typer.Option(help="直接按最近参考归属，扫描距离阈值")] = False,
) -> None:
    """每角色 1/2 条参考重复划分，排除参考后与原分组公平对照。"""
    from avs.evaluation.references import reference_experiment

    result = reference_experiment(groups, annotation, out, role, nearest)
    typer.echo(f"完成 {len(result['results'])} 次参考实验 -> {out}")


@app.command()
def diagnose(
    episodes: Annotated[list[Path], typer.Argument(help="固定的集目录")],
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的诊断输出目录")],
    groups: Annotated[Path | None, typer.Option(help="当前分组文件，用于区分组内/组间错误")] = None,
) -> None:
    """用两模型缓存和人工标签做近邻与距离诊断，导出可试听错误实例。"""
    from avs.embeddings.extract import MODELS
    from avs.evaluation.diagnose import diagnose as run_diagnosis

    result = run_diagnosis(episodes, annotation, list(MODELS), out, groups)
    for model, own in result["models"].items():
        typer.echo(
            f"{model}: {own['retrieval']['queries']} 次查询，"
            f"Top-1 同角色 {own['retrieval']['top1_hit_rate']}"
        )
    typer.echo(f"诊断 -> {out}")


@app.command()
def scores(
    episodes: Annotated[list[Path], typer.Argument(help="固定的集目录")],
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的分离度报告 JSON")],
    model: Annotated[list[str] | None, typer.Option(help="只比较这些模型，默认两个都比")] = None,
    norm: Annotated[list[str] | None, typer.Option(help="要比较的归一化，可重复")] = None,
    window: Annotated[float, typer.Option(help="读哪一档听音窗口算出的声纹")] = 0.0,
) -> None:
    """比较原始余弦与分数归一化下，同一角色和不同角色的配对分不分得开。"""
    from avs.embeddings.extract import MODELS
    from avs.evaluation.scores import compare_norms

    report = compare_norms(episodes, annotation, model or list(MODELS), out, norm, window)
    for entry in report["results"]:
        own = entry["overall"]
        typer.echo(
            f"{entry['model']:22s} {entry['norm']:7s} "
            f"排序正确率 {own['auc']}  相等错误率 {own['eer']}"
        )
    typer.echo(f"{report['pairs']} 对标签配对 -> {out}")


@app.command()
def coverage(
    episode: Path,
    subtitle: Annotated[Path, typer.Option(help="这一集的 ASS 字幕")],
    out: Annotated[Path, typer.Option(help="新的核对输出目录")],
    pad: Annotated[float, typer.Option(help="切音频时前后各留几秒，便于听清")] = 0.0,
) -> None:
    """找出字幕里没有对应片段的台词，按原因切成音频供试听。"""
    from avs.evaluation.coverage import coverage as check

    report = check(episode, subtitle, out, pad)
    own = report["summary"]
    typer.echo(
        f"{report['episode']}：对白 {own['dialogue_lines']} 行，"
        f"有片段 {own['lines_with_clip']} 行，没片段 {own['lines_without_clip']} 行"
        f"（短于 {report['floor_seconds']} 秒 {own['below_floor']} 行，"
        f"够长却没切出 {own['no_speech_found']} 行）"
    )
    typer.echo(
        f"整段没有片段却有台词的空洞 {own['holes']} 处，共 {own['hole_seconds'] / 60:.1f} 分钟，"
        f"里面有 {own['hole_dialogue_seconds']:.0f} 秒台词"
    )
    typer.echo(f"偏移 {report['offset_seconds']:+.2f} 秒，音频与清单 -> {out}")


@app.command()
def export(groups: Path, out: Annotated[Path, typer.Option(help="新的音频目录")]) -> None:
    """从原采样率人声轨导出每个身份组，不设音质门槛。"""
    result = pipeline.export_groups(groups, out)
    typer.echo(f"导出 {result['files']} 条，共 {result['total_sec']} 秒 -> {out}")


@app.command()
def label(
    episode: Path,
    archive: Annotated[Path, typer.Option(help="人工归档，例如 annotations/ep03.json")],
    count: int = 50,
    port: int = 8765,
    plan: Annotated[
        Path | None, typer.Option(help="标注计划；给了就只标计划里的片段，忽略 --count")
    ] = None,
    known: Annotated[
        list[Path] | None,
        typer.Option(help="页面词表用的已有归档，可重复；默认取计划里记的那几份"),
    ] = None,
    every: Annotated[
        bool, typer.Option("--all", help="标这一集的全部片段，按时间顺序；忽略 --count")
    ] = False,
    video: Annotated[
        Path | None, typer.Option(help="这一集的视频；给了就在页面上放对应画面，按需现切")
    ] = None,
) -> None:
    """抽样、按计划或整集取片段，对照画面标角色名，逐条存入归档。"""
    from avs.labeling import run

    run(episode, archive, count, port, plan, known, every, video)


@app.command()
def label_plan(
    candidate: Annotated[Path, typer.Option(help="候选分组，例如分两步")],
    baseline: Annotated[Path, typer.Option(help="现行默认分组，用于标出归属不同的片段")],
    annotation: Annotated[list[Path], typer.Option(help="已有人工归档，可重复提供")],
    out: Annotated[Path, typer.Option(help="新的标注计划 JSON")],
) -> None:
    """列出候选把哪些还没标过的短片段挂进了多条组，作为下一轮标注的范围。"""
    from avs.labeling import build_plan

    plan = build_plan(candidate, baseline, annotation, out)
    for episode, own in plan["summary"].items():
        typer.echo(f"{episode}: {own['clips']} 条待标，其中 {own['moved']} 条两套分组归属不同")
    typer.echo(f"计划 -> {out}")
