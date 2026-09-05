"""avs 命令行入口。各子命令对应管线的一个阶段，读写同一张 segments 表。"""

from __future__ import annotations

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
