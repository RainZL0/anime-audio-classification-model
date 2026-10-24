"""The command-line entry point: add episodes and open the labeling interface."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Annotated

import typer

from avoc import pipeline
from avoc.language import say
from avoc.stages.captions import marked_note

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
STYLES_HELP = (
    "Subtitle styles that hold the dialogue, separated by commas, for example "
    '"Default,Default - Top"; if omitted, they are picked automatically. '
    "See them with: avoc styles SUBTITLES"
)


SPOKEN_HELP = (
    "Language spoken in the video: ja, zh, en or ko. The voices are taken from the audio track "
    "tagged with it, and exported text must be in it. If omitted, it is read from the audio "
    "track's tag, and Japanese is assumed when there is none"
)


def style_list(text: str | None) -> list[str] | None:
    """`--styles` as a list. ASS style names cannot contain commas, so commas separate them."""
    if text is None:
        return None
    return [name.strip() for name in text.split(",") if name.strip()]


@app.command()
def doctor() -> None:
    """Check the runtime environment: GPU, FFmpeg, model files, and the Hugging Face token."""
    from avoc.doctor import checks

    problems = 0
    for check in checks(Path.cwd()):
        problems += check.required and not check.ok
        mark = (
            "[ok]"
            if check.ok
            else "[untested]"
            if check.topic == "system"
            else "[missing]"
            if check.required
            else "[optional]"
        )
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
        Path,
        typer.Option(
            help="Main subtitles of this episode; clips are cut from them. Best in the "
            "language spoken (usually Japanese)"
        ),
    ],
    name: Annotated[
        str | None,
        typer.Option(
            help="Episode name, for example ep03; if omitted, the next unused epNN is used"
        ),
    ] = None,
    display_subs: Annotated[
        Path | None,
        typer.Option(
            help="Subtitles in a language you read (usually a translation), shown while labeling; "
            "export never takes text from them"
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
    styles: Annotated[str | None, typer.Option(help=STYLES_HELP)] = None,
    spoken: Annotated[str | None, typer.Option(help=SPOKEN_HELP)] = None,
) -> None:
    """Add one episode: cut clips, compute the voiceprints the interface needs, and attach the
    secondary subtitles if given. If it stops partway, run the same command again to continue."""
    import os

    # When the interface runs this command, it asks for our own lines to be marked, so it can
    # tell them apart from what the libraries print.
    mark = pipeline.PROGRESS_MARK if os.environ.get("AVOC_MARK_PROGRESS") else ""
    from avoc.app.adding import STOP_WITH_INTERFACE, stop_with_interface

    if os.environ.get(STOP_WITH_INTERFACE, "").isdigit():
        stop_with_interface(int(os.environ[STOP_WITH_INTERFACE]))

    def report(line: str) -> None:
        typer.echo(mark + line)

    try:
        result = pipeline.add_episode(
            workspace,
            video,
            subs,
            name,
            audio,
            offset,
            device,
            report=report,
            styles=style_list(styles),
            spoken=spoken,
            display_subtitles=display_subs,
        )
    except ValueError as exc:
        typer.echo(say(f"出错：{exc}", f"Error: {exc}"), err=True)
        raise typer.Exit(1) from exc
    report(
        say(
            f"{result['episode']} 加好了，{result['segments']} 个片段",
            f"{result['episode']} added, {result['segments']} clips",
        )
    )
    if not mark:  # Run from the interface, it is already open.
        typer.echo(say("打开界面：", "To open the interface:"))
        typer.echo(f"  uv run avoc app {workspace}")


@app.command()
def prepare(
    video: Annotated[Path, typer.Argument(help="Video of this episode, required")],
    subs: Annotated[Path, typer.Option(help="Matching main subtitles, required")],
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
    styles: Annotated[str | None, typer.Option(help=STYLES_HELP)] = None,
    spoken: Annotated[str | None, typer.Option(help=SPOKEN_HELP)] = None,
) -> None:
    """Prepare an episode: extract the audio, separate the vocals, align the subtitles, and make one
    clip per dialogue line."""
    typer.echo(
        pipeline.prepare(
            video, subs, out, name, vocals, offset, device, audio, style_list(styles), spoken
        )
    )


@app.command("styles")
def show_styles(
    subtitles: Annotated[Path, typer.Argument(help="A subtitle file (ASS, SRT and so on)")],
) -> None:
    """Show the styles in a subtitle file: how many lines each has, when they appear, and a few
    sample lines. Styles marked * are the ones picked as dialogue when --styles is not given."""
    from avoc.stages.subtitle import describe_styles

    try:
        found = describe_styles(subtitles)
    except ValueError as exc:
        typer.echo(say(f"出错：{exc}", f"Error: {exc}"), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{found['format']}, {found['encoding']}")

    def clock(seconds: float) -> str:
        return f"{int(seconds // 60)}:{int(seconds % 60):02d}"

    for style in found["styles"]:
        mark = "*" if style["name"] in found["picked"] else " "
        typer.echo(
            f"{mark} {style['name']}: {style['lines']} "
            + say("行", "lines")
            + f", {clock(style['first'])}-{clock(style['last'])}"
        )
        for sample in style["samples"]:
            typer.echo(f"      {sample[:60]}")
    if found["marked"]:
        typer.echo(marked_note(found["marked"]))


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


@app.command("set-display-subtitles")
def set_display_subtitles(
    episode: Path,
    subtitles: Annotated[
        Path,
        typer.Argument(help="Subtitles in a language you read, usually a translation"),
    ],
) -> None:
    """Add subtitles that are only shown while labeling, for an episode cut from subtitles in a
    language you do not read. The offset is measured automatically, and the command refuses if the
    two do not line up."""
    result = pipeline.attach_display_subtitles(episode, subtitles)
    typer.echo(
        f"{result['episode']}: offset {result['display_subtitle_offset']} seconds, "
        f"overlap with the clip subtitles {result['display_subtitle_agreement']:.0%}"
    )


@app.command("set-spoken-language")
def set_spoken_language(
    episode: Path,
    language: Annotated[str, typer.Argument(help="ja, zh, en or ko")],
) -> None:
    """Correct the language spoken in an episode, when the audio track's tag was wrong or
    missing. The voices already cut stay; to cut from another audio track, add the episode again
    with --spoken."""
    try:
        result = pipeline.set_spoken_language(episode, language)
    except ValueError as exc:
        typer.echo(say(f"出错：{exc}", f"Error: {exc}"), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{result['episode']}: spoken language {result['spoken_language']}")


@app.command("borrow-labels")
def borrow_labels(
    workspace: Annotated[Path, typer.Argument(help="The workspace that borrows")],
    other: Annotated[
        Path | None, typer.Argument(help="The workspace whose labels are borrowed")
    ] = None,
    stop: Annotated[bool, typer.Option("--stop", help="Stop borrowing")] = False,
) -> None:
    """Let the machine learn from another workspace's labels too, such as the same show cut from
    other subtitles. They only help it guess; nothing is copied into this workspace's labels. Stop
    with --stop once enough lines are labeled here."""
    from avoc.app import borrowing

    if stop:
        done = borrowing.stop(workspace)
        typer.echo(
            say("不再借用别处的标注", "No longer borrowing labels")
            if done
            else say("本来就没借用", "Nothing was borrowed")
        )
        return
    if other is None:
        typer.echo(say("出错：要给出被借用的工作区", "Error: give the workspace to borrow from"),
                   err=True)  # fmt: skip
        raise typer.Exit(1)
    try:
        added = borrowing.start(workspace, other)
    except ValueError as exc:
        typer.echo(say(f"出错：{exc}", f"Error: {exc}"), err=True)
        raise typer.Exit(1) from exc
    typer.echo(say(f"借用 {other} 的标注", f"Borrowing the labels of {other}"))
    if added:
        typer.echo(
            say(
                f"新加的目标角色：{'、'.join(added)}",
                f"Target characters added: {', '.join(added)}",
            )
        )
    typer.echo(say("重开 avoc app 后生效", "Restart avoc app for it to take effect"))


def _serve_reloaded(port: int) -> None:
    """The server of `avoc app --reload`, run in a new process after each change."""
    import uvicorn

    uvicorn.run("avoc.app.server:reloaded_app", factory=True, host="127.0.0.1", port=port,
                log_level="warning")  # fmt: skip


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
    reload: Annotated[
        bool,
        typer.Option(
            help="For development: restart the server when a Python file of avoc changes. "
            "Each restart loads the workspace again and stops an episode being added"
        ),
    ] = False,
) -> None:
    """Open the labeling and correction interface."""
    import os
    import webbrowser

    import uvicorn

    from avoc.app.server import RELOAD_MODELS, RELOAD_WORKSPACE, AppState, create_app
    from avoc.app.workspace import DEFAULT_MODELS

    if reload:
        # The server runs in a child process that is started again after each change, so it reads
        # its settings from the environment; see `reloaded_app`.
        os.environ[RELOAD_WORKSPACE] = str(workspace.resolve())
        os.environ[RELOAD_MODELS] = ",".join(model or DEFAULT_MODELS)
        url = f"http://127.0.0.1:{port}/"
        typer.echo(f"Open {url} (restarts when avoc's Python files change)")
        if open_browser:
            import threading

            threading.Timer(4.0, webbrowser.open, args=[url]).start()
        # Not uvicorn's own reload: on Windows it stops the old server with Ctrl+C, which never
        # arrives when the server has no console window of its own, so it never restarted.
        # watchfiles ends the old process outright and starts a new one.
        from watchfiles import PythonFilter, run_process

        run_process(
            Path(__file__).parent,
            target=_serve_reloaded,
            args=(port,),
            watch_filter=PythonFilter(),
            callback=lambda _: typer.echo("avoc's Python files changed, restarting"),
        )
        return

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
