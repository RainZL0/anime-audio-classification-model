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
def embed(
    episodes: Annotated[list[Path], typer.Argument(help="一集或多集目录")],
    model: str = "redimnet2-b6",
    device: str = "cuda",
) -> None:
    """计算全量片段声纹，输入未变时复用缓存。"""
    for episode in episodes:
        typer.echo(pipeline.embed(episode, model, device))


@app.command()
def group(
    episodes: Annotated[list[Path], typer.Argument(help="要一起分组的集目录")],
    out: Annotated[Path, typer.Option(help="新的分组 JSON 文件")],
    threshold: float = 0.5,
    model: str = "redimnet2-b6",
    method: Annotated[
        str, typer.Option(help="连接规则：average/single/complete/mutual_knn")
    ] = "average",
) -> None:
    """只读取缓存进行全局分组，小组保留；可以反复调整阈值和连接规则。"""
    result = pipeline.group(episodes, out, threshold, model, method)
    typer.echo(result["summary"])
    typer.echo(f"分组 -> {out}")


@app.command()
def evaluate(
    groups: Path,
    annotation: Annotated[list[Path], typer.Option(help="人工身份归档，可重复提供")],
    out: Path = Path("runs/evaluation.json"),
) -> None:
    """精确对照人工身份，统计错合与漏合。"""
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
) -> None:
    """比较缓存模型与连接规则在 0.20—0.90 阈值下的错合与漏合；仅用于探索。"""
    from avs.embeddings.extract import MODELS
    from avs.evaluation.compare import compare as compare_models

    result = compare_models(
        episodes, annotation, model or list(MODELS), [i / 100 for i in range(20, 91)], out, method
    )
    typer.echo(f"比较 {len(result['results'])} 个设置 -> {out}")


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
) -> None:
    """从全量片段随机抽样，对照画面标角色名，逐条存入归档。"""
    from avs.labeling import run

    run(episode, archive, count, port)
