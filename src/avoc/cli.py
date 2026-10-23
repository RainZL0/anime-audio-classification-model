"""The command-line entry point: add episodes and open the labeling interface."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Annotated

import typer

from avoc import pipeline
from avoc.language import say

app = typer.Typer(
    name="avoc",
    help="Cut clips by subtitles, then label and export one character's lines.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    # The default encoding of a Windows pipe may not be able to show every character.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


DEVICE_HELP = "cuda, cpu, or auto (uses cuda if there is an NVIDIA GPU)"


@app.command()
def doctor() -> None:
    """Check the runtime environment: GPU, FFmpeg, model files, and the Hugging Face token."""
    from avoc.doctor import checks

    problems = 0
    for check in checks(Path.cwd()):
        problems += check.required and not check.ok
        mark = "[ok]" if check.ok else "[missing]" if check.required else "[optional]"
        fix = f"\n     {check.fix}" if check.fix and not check.ok else ""
        typer.echo(f"{mark} {check.text}{fix}")
    typer.echo(
        "All checks passed" if problems == 0 else f"Found {problems} item(s) that need attention"
    )


@app.command()
def add(
    workspace: Annotated[
        Path, typer.Argument(help="Workspace folder; episodes are kept in its episodes/ folder")
    ],
    video: Annotated[Path, typer.Argument(help="Video of this episode")],
    subs: Annotated[
        Path, typer.Option(help="Dialogue subtitles of this episode; clips are cut from them")
    ],
    name: Annotated[
        str | None,
        typer.Option(
            help="Episode name, for example ep03; if omitted, the next unused epNN is used"
        ),
    ] = None,
    text_subs: Annotated[
        Path | None,
        typer.Option(
            help="Separate text subtitles (usually the Japanese original); export takes the text "
            "from them"
        ),
    ] = None,
    audio: Annotated[
        Path | None,
        typer.Option(help="Separate original audio track; if omitted, it is taken from the video"),
    ] = None,
    offset: Annotated[
        float | None,
        typer.Option(
            help="Seconds to add to the subtitles; if omitted, it is measured automatically, which "
            "needs a Hugging Face token"
        ),
    ] = None,
    device: Annotated[str, typer.Option(help=DEVICE_HELP)] = "auto",
) -> None:
    """Add one episode: cut clips, compute the voiceprints the interface needs, and attach text
    subtitles if given. If it stops partway, run the same command again to continue."""
    try:
        result = pipeline.add_episode(
            workspace, video, subs, name, text_subs, audio, offset, device, report=typer.echo
        )
    except ValueError as exc:
        typer.echo(say(f"出错：{exc}", f"Error: {exc}"), err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        say(
            f"{result['episode']} 加好了，{result['segments']} 个片段。打开界面：",
            f"{result['episode']} added, {result['segments']} clips. To open the interface:",
        )
    )
    typer.echo(f"  uv run avoc app {workspace}")


@app.command()
def prepare(
    video: Annotated[Path, typer.Argument(help="Video of this episode, required")],
    subs: Annotated[Path, typer.Option(help="Matching dialogue subtitles, required")],
    out: Annotated[Path, typer.Option(help="New episode folder")],
    name: Annotated[str, typer.Option(help="Unique episode name, for example ep03")],
    audio: Annotated[
        Path | None,
        typer.Option(help="Separate original audio track; if omitted, it is taken from the video"),
    ] = None,
    vocals: Annotated[
        Path | None, typer.Option(help="Reuse an existing vocal track at its original sample rate")
    ] = None,
    offset: Annotated[
        float | None,
        typer.Option(help="Seconds to add to the subtitles; if omitted, aligned automatically"),
    ] = None,
    device: Annotated[str, typer.Option(help=DEVICE_HELP)] = "auto",
) -> None:
    """Prepare an episode: extract the audio, separate the vocals, align the subtitles, and make one
    clip per dialogue line."""
    typer.echo(pipeline.prepare(video, subs, out, name, vocals, offset, device, audio))


@app.command()
def embed(
    episodes: Annotated[list[Path], typer.Argument(help="One or more episode folders")],
    model: str = "redimnet2-b6",
    device: Annotated[str, typer.Option(help=DEVICE_HELP)] = "auto",
) -> None:
    """Compute voiceprints for all clips. The cache is reused when the input has not changed."""
    for episode in episodes:
        typer.echo(pipeline.embed(episode, model, device))


@app.command("set-video")
def set_video(
    episode: Path,
    video: Annotated[
        Path,
        typer.Argument(help="Video file of this episode, on the same timeline as the audio track"),
    ],
) -> None:
    """Record the video file for an episode. Refuse if its duration does not match the original
    audio track, so pictures are never matched to the wrong speaker."""
    result = pipeline.attach_video(episode, video)
    typer.echo(
        f"{result['episode']}: video {result['video_seconds']} seconds, "
        f"audio {result['audio_seconds']} seconds"
    )


@app.command("set-subtitles")
def set_subtitles(
    episode: Path,
    subtitles: Annotated[
        Path, typer.Argument(help="The subtitle file that was used to cut clips for this episode")
    ],
) -> None:
    """Add subtitles to early episodes that did not record them. The interface needs them to show
    dialogue. The offset is worked out from the existing clips."""
    result = pipeline.attach_subtitles(episode, subtitles)
    typer.echo(
        f"{result['episode']}: offset {result['offset']} seconds, "
        f"{result['matched']:.1%} of clips matched"
    )


@app.command("set-text-subtitles")
def set_text_subtitles(
    episode: Path,
    subtitles: Annotated[
        Path,
        typer.Argument(
            help="Subtitles that supply the dialogue text for export, usually the Japanese original"
        ),
    ],
) -> None:
    """Add a second subtitle file to an episode. Export takes the dialogue text from it. The offset
    is measured automatically, and the command refuses if the two do not line up."""
    result = pipeline.attach_text_subtitles(episode, subtitles)
    typer.echo(
        f"{result['episode']}: offset {result['text_subtitle_offset']} seconds, "
        f"overlap with the clip subtitles {result['text_subtitle_agreement']:.0%}, "
        f"{result['matched']:.1%} of clips match a dialogue line"
    )


@app.command("app")
def run_app(
    workspace: Annotated[Path, typer.Argument(help="Workspace folder, which contains episodes/")],
    port: int = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the browser after starting")
    ] = True,
    model: Annotated[
        list[str] | None,
        typer.Option(
            help="Voiceprint models, can be given more than once; if omitted, the three are "
            "combined"
        ),
    ] = None,
) -> None:
    """Open the labeling and correction interface."""
    import webbrowser

    import uvicorn

    from avoc.app.server import AppState, create_app
    from avoc.app.workspace import DEFAULT_MODELS

    state = AppState(workspace, tuple(model) if model else DEFAULT_MODELS)
    typer.echo(
        f"{len(state.workspace.episodes)} episodes, {len(state.workspace.clips)} clips, "
        f"{state.trained['labels']} labels used for training"
    )
    for name, reason in state.workspace.skipped.items():
        typer.echo(f"Could not load {name}: {reason}")
    if not state.workspace.episodes:
        typer.echo(
            f"No episode in the workspace can be used yet. "
            f"Add one first: uv run avoc add {workspace} VIDEO --subs SUBTITLES"
        )
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"Open {url}")
    if open_browser:
        import threading

        # Wait for the server to start before opening the browser, otherwise the first view is a
        # page that cannot connect.
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(state), host="127.0.0.1", port=port, log_level="warning")
