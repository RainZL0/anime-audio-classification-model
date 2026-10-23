"""The single command-line entry point for subtitle-based speaker classification."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Annotated

import typer

from avs import pipeline
from avs.project import write_json

app = typer.Typer(
    name="avs",
    help="Cut clips by subtitles, and group the voices of the same character together.",
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
    import shutil

    import torch

    from avs.audio import SEPARATION_MODEL

    problems = 0

    def report(ok: bool, text: str, fix: str = "", required: bool = True) -> None:
        nonlocal problems
        problems += required and not ok
        mark = "[ok]" if ok else "[missing]" if required else "[optional]"
        typer.echo(f"{mark} {text}" + (f"\n     {fix}" if fix and not ok else ""))

    cuda = torch.cuda.is_available()
    gpu = f", {torch.cuda.get_device_name(0)}" if cuda else ""
    report(
        cuda,
        f"torch {torch.__version__}, CUDA {'available' if cuda else 'not available'}{gpu}",
        "No usable NVIDIA GPU was found, so the CPU will be used. It works, but separating vocals "
        "for one episode is much slower",
        required=False,
    )
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        report(
            bool(found),
            f"{tool}: {found or 'not found'}",
            "Install FFmpeg and add its bin folder to PATH",
        )
    model = Path("models") / SEPARATION_MODEL
    report(
        True,
        f"Voice separation model: {model}"
        if model.exists()
        else "Voice separation model: will be downloaded automatically the first time it is used",
    )
    token = pipeline.has_hf_token()
    report(
        token,
        f"Hugging Face token: {'present' if token else 'missing'}",
        "Only needed when --offset is not given and the subtitle offset should be measured "
        "automatically: " + pipeline.TOKEN_HOWTO,
        required=False,
    )
    free = shutil.disk_usage(Path.cwd()).free / 2**30
    report(
        free >= 5,
        f"Free space on the current disk: {free:.0f} GB",
        "One processed episode takes about 0.5 GB, so leave enough space",
    )
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
            workspace, video, subs, name, text_subs, audio, offset, device, say=typer.echo
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{result['episode']} added, {result['segments']} clips. To open the interface:")
    typer.echo(f"  uv run avs app {workspace}")


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
def extend(
    episode: Path,
    subtitle: Annotated[Path, typer.Option(help="ASS subtitles for this episode")],
    floor: Annotated[
        float,
        typer.Option(
            help="Lines shorter than this many seconds are not filled in, because no reliable "
            "voiceprint can be computed"
        ),
    ] = 0.2,
) -> None:
    """Add dialogue lines that have no matching clip from the subtitles to the clip table. Existing
    clips are not touched, so labels do not need to be redone."""
    result = pipeline.extend_segments(episode, subtitle, floor)
    typer.echo(
        f"{result['episode']}: {result['before']} -> {result['after']} clips, "
        f"added {result['added']} (shortest {result['shortest_added']} seconds), "
        f"{result['too_short']} more were shorter than "
        f"{result['floor_seconds']} seconds and not added"
    )
    typer.echo("The clip table changed, so the voiceprint cache is now stale. Run embed again")


@app.command()
def embed(
    episodes: Annotated[list[Path], typer.Argument(help="One or more episode folders")],
    model: str = "redimnet2-b6",
    device: Annotated[str, typer.Option(help=DEVICE_HELP)] = "auto",
    window: Annotated[
        float,
        typer.Option(
            help="Minimum listening window in seconds. Short clips borrow audio from their "
            "neighbours on both sides to reach it. 0 means no borrowing"
        ),
    ] = 0.0,
) -> None:
    """Compute voiceprints for all clips. The cache is reused when the input has not changed."""
    for episode in episodes:
        typer.echo(pipeline.embed(episode, model, device, window))


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


@app.command("import-labels")
def import_labels(
    workspace: Annotated[Path, typer.Argument(help="Workspace folder, which contains episodes/")],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    target: Annotated[
        list[str] | None,
        typer.Option(
            help="After import, keep only these target characters and set the rest to 'other'. Can "
            "be given more than once"
        ),
    ] = None,
) -> None:
    """Import the names from the human archive into the interface's label records. Only use this
    while the label records are still empty."""
    from avs.app.labels import LabelStore, import_archives
    from avs.app.workspace import episode_dirs
    from avs.project import load_episode, time_key

    store = LabelStore(workspace / "labels")
    if store.batches:
        raise typer.BadParameter(
            "The label records already contain data, so nothing was imported again"
        )
    by_time, sources = {}, {}
    for directory in episode_dirs(workspace):
        episode, rows = load_episode(directory)
        sources[Path(episode["vocals"]).name] = episode["name"]
        by_time.update({(episode["name"], time_key(r)): r["id"] for r in rows})
    count = import_archives(store, annotation, by_time, sources)
    typer.echo(f"Imported {count} labels, {len(store.roles)} characters -> {store.folder}")
    if target:
        migrate_targets(workspace, target)


@app.command("migrate-targets")
def migrate_targets(
    workspace: Annotated[Path, typer.Argument(help="Workspace folder, which contains labels/")],
    target: Annotated[
        list[str], typer.Option(help="Target characters to keep, can be given more than once")
    ],
) -> None:
    """Keep only the given target characters. Labels of all other characters are set to 'other'. The
    label records are archived unchanged before the change."""
    from datetime import datetime

    from avs.app.labels import LabelStore, migrate_to_targets

    store = LabelStore(workspace / "labels")
    archive = store.folder / f"archive-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        count = migrate_to_targets(store, target, archive)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{count} labels set to 'other'. Target characters: {
            ', '.join(target)
        }; original archived in {archive}"
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

    from avs.app.server import AppState, create_app
    from avs.app.workspace import DEFAULT_MODELS

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
            f"Add one first: uv run avs add {workspace} VIDEO --subs SUBTITLES"
        )
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"Open {url}")
    if open_browser:
        import threading

        # Wait for the server to start before opening the browser, otherwise the first view is a
        # page that cannot connect.
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(state), host="127.0.0.1", port=port, log_level="warning")


@app.command()
def group(
    episodes: Annotated[list[Path], typer.Argument(help="Episode folders to group together")],
    out: Annotated[Path, typer.Option(help="New grouping JSON file")],
    threshold: Annotated[
        float | None,
        typer.Option(help="Distance threshold; if omitted, this model's own default is used"),
    ] = None,
    model: str = "anime-va",
    method: Annotated[
        str, typer.Option(help="Linking rule: average/single/complete/mutual_knn/two_stage")
    ] = "average",
    relative: Annotated[
        bool,
        typer.Option(
            "--relative",
            help="The threshold is computed from this pool's own distances, not a fixed value; not "
            "yet independently tested",
        ),
    ] = False,
) -> None:
    """Group globally using only the cached voiceprints. Small groups are kept. You can adjust the
    threshold and linking rule again and again."""
    from avs.embeddings.extract import DEFAULT_THRESHOLDS

    if relative:
        if threshold is not None:
            raise typer.BadParameter(
                "--relative computes the threshold itself, so it cannot be combined with "
                "--threshold"
            )
        threshold = pipeline.relative_threshold(episodes, model)
        typer.echo(
            f"Threshold computed from the pool: {threshold:.4f} "
            f"(the fixed value is {DEFAULT_THRESHOLDS[model]})"
        )
    elif threshold is None:
        threshold = DEFAULT_THRESHOLDS.get(model, 0.5)
        typer.echo(f"No threshold given, using the default for {model}: {threshold}")
    result = pipeline.group(episodes, out, threshold, model, method)
    typer.echo(result["summary"])
    typer.echo(f"Grouping -> {out}")


@app.command()
def evaluate(
    groups: Path,
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Path = Path("runs/evaluation.json"),
) -> None:
    """Compare exactly against human identities, and count wrong merges and missed merges."""
    from avs.evaluation.identity import evaluate as score

    result = score(groups, annotation)
    write_json(out, result)
    typer.echo(result["metrics"])
    typer.echo(f"Report -> {out}")


@app.command()
def compare(
    episodes: Annotated[list[Path], typer.Argument(help="Fixed episode folders")],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Annotated[Path, typer.Option(help="New comparison report JSON")],
    model: Annotated[
        list[str] | None,
        typer.Option(help="Only compare these models; by default both are compared"),
    ] = None,
    method: Annotated[
        list[str] | None,
        typer.Option(help="Linking rules, can be given more than once; default is average"),
    ] = None,
    low: Annotated[float, typer.Option(help="Lower bound of the threshold scan")] = 0.20,
    high: Annotated[float, typer.Option(help="Upper bound of the threshold scan")] = 0.90,
) -> None:
    """Compare cached models and linking rules over a range of thresholds, counting wrong merges and
    missed merges. For exploration only.

    The default range was set for ReDimNet. Different models have different similarity scales.
    Before switching models, check where the distances of the same character fall, then choose a
    range. Copying someone else's range would scan a part where nothing useful can be seen.
    """
    from avs.embeddings.extract import MODELS
    from avs.evaluation.compare import compare as compare_models

    if not 0 < low < high <= 2:
        raise typer.BadParameter("The threshold range must satisfy 0 < low < high <= 2")
    grid = [i / 100 for i in range(round(low * 100), round(high * 100) + 1)]
    result = compare_models(episodes, annotation, model or list(MODELS), grid, out, method)
    typer.echo(f"Compared {len(result['results'])} settings -> {out}")


@app.command()
def drift(
    episodes: Annotated[list[Path], typer.Argument(help="Fixed episode folders")],
    scored: Annotated[
        str,
        typer.Option(
            help="Episode name of the scored episode; it is always included in full in the pool"
        ),
    ],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Annotated[Path, typer.Option(help="New drift report JSON")],
    model: str = "anime-va",
    threshold: Annotated[
        float | None,
        typer.Option(help="Fixed threshold to examine; if omitted, the model's default is used"),
    ] = None,
    multiplier: Annotated[
        float | None,
        typer.Option(
            help="Multiplier used when the threshold is set from the pool; if omitted, the model's "
            "default is used"
        ),
    ] = None,
    steps: Annotated[int, typer.Option(help="How many pool sizes to try")] = 7,
    seeds: Annotated[
        int,
        typer.Option(
            help="How many random draws of clips from other episodes to make at each size"
        ),
    ] = 8,
) -> None:
    """Measure how the scores change as the clip pool grows, comparing a fixed threshold with a
    threshold set from the pool.

    The scored episode is always included in full, and only clips from other episodes are added.
    Each size faces the same labels and the same pairs, so the scores can be compared directly. What
    matters is whether wrong merges stay stable, not how many pairs get linked.
    """
    from avs.evaluation.drift import drift as run_drift

    report = run_drift(
        episodes, scored, annotation, out, model, threshold, multiplier, steps=steps, seeds=seeds
    )
    typer.echo(
        f"{report['labeled_clips']} labels, {report['roles']} characters; "
        f"scoring only looks at {scored}"
    )
    typer.echo(
        "Each row is one pool size, with the two threshold methods side by side. What matters is "
        "whether wrong merges stay stable"
    )
    for row in report["summary"]:
        typer.echo(
            f"Pool of {row['pool_clips']:>5} clips: "
            f"fixed threshold {row['fixed_threshold']:.3f}, linked {row['fixed_correct_pairs']:.0f}"
            f", wrong merges {row['fixed_false_merges']:.0f}"
            f"; pool threshold {row['relative_threshold']:.4f}"
            f", linked {row['relative_correct_pairs']:.0f}"
            f", wrong merges {row['relative_false_merges']:.0f}"
        )
    typer.echo(f"Report -> {out}")


@app.command("classify-check")
def classify_check(
    episodes: Annotated[
        list[Path], typer.Argument(help="Episode folders for the training set and the test set")
    ],
    test: Annotated[
        str,
        typer.Option(
            help="Episode name of the one under test; its labels are not used for training"
        ),
    ],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Annotated[Path, typer.Option(help="New classification check report JSON")],
    model: Annotated[
        list[str] | None,
        typer.Option(
            help="Voiceprint models, can be given more than once; multiple models are combined"
        ),
    ] = None,
) -> None:
    """Check by holding out whole episodes: train on the labels of the other episodes, then assign
    each clip of the test episode directly to a character name."""
    from avs.evaluation.classify import classify_check as run_check

    report = run_check(episodes, test, annotation, out, model or ["anime-va"])
    typer.echo(
        f"{'+'.join(report['models'])}: trained on "
        f"{sum(report['train_episodes'].values())} labels, "
        f"tested {report['test_clips']} clips, of which "
        f"{report['unseen_role_clips']} have a character that is not in the training set"
    )
    for method, own in report["results"].items():
        tiers = ", ".join(
            f"{k} {v['accuracy']} ({v['clips']} clips)" for k, v in own["by_duration"].items()
        )
        confident = ", ".join(f"{k} {v}" for k, v in own["by_confidence"].items())
        typer.echo(f"{method}: overall {own['accuracy']}; by confidence {confident}")
        typer.echo(f"  by duration {tiers}")
    typer.echo(f"Report -> {out}")


@app.command()
def references(
    groups: Path,
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    role: Annotated[
        list[str],
        typer.Option(
            help="Character names to test reference groups for, can be given more than once"
        ),
    ],
    out: Annotated[Path, typer.Option(help="New experiment output folder")],
    nearest: Annotated[
        bool,
        typer.Option(
            help="Assign each clip directly to its nearest reference, and scan the distance "
            "threshold"
        ),
    ] = False,
) -> None:
    """Repeated split: for each character, use 1 or 2 clips as references, then exclude them and
    compare fairly with the original grouping."""
    from avs.evaluation.references import reference_experiment

    result = reference_experiment(groups, annotation, out, role, nearest)
    typer.echo(f"Finished {len(result['results'])} reference experiments -> {out}")


@app.command()
def diagnose(
    episodes: Annotated[list[Path], typer.Argument(help="Fixed episode folders")],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Annotated[Path, typer.Option(help="New diagnosis output folder")],
    groups: Annotated[
        Path | None,
        typer.Option(
            help="Current grouping file; used to tell errors inside a group from errors between "
            "groups"
        ),
    ] = None,
) -> None:
    """Run nearest-neighbour and distance diagnostics using both models' caches and the human
    labels, and export wrong cases you can listen to."""
    from avs.embeddings.extract import MODELS
    from avs.evaluation.diagnose import diagnose as run_diagnosis

    result = run_diagnosis(episodes, annotation, list(MODELS), out, groups)
    for model, own in result["models"].items():
        typer.echo(
            f"{model}: {own['retrieval']['queries']} queries, "
            f"top-1 same-character rate {own['retrieval']['top1_hit_rate']}"
        )
    typer.echo(f"Diagnosis -> {out}")


@app.command()
def scores(
    episodes: Annotated[list[Path], typer.Argument(help="Fixed episode folders")],
    annotation: Annotated[
        list[Path],
        typer.Option(help="Archive of human-labeled identities, can be given more than once"),
    ],
    out: Annotated[Path, typer.Option(help="New separation report JSON")],
    model: Annotated[
        list[str] | None,
        typer.Option(help="Only compare these models; by default both are compared"),
    ] = None,
    norm: Annotated[
        list[str] | None,
        typer.Option(help="Normalizations to compare, can be given more than once"),
    ] = None,
    window: Annotated[
        float, typer.Option(help="Which listening window's voiceprints to read")
    ] = 0.0,
) -> None:
    """Compare whether pairs from the same character and pairs from different characters can be told
    apart, with raw cosine similarity and with score normalization."""
    from avs.embeddings.extract import MODELS
    from avs.evaluation.scores import compare_norms

    report = compare_norms(episodes, annotation, model or list(MODELS), out, norm, window)
    for entry in report["results"]:
        own = entry["overall"]
        typer.echo(
            f"{entry['model']:22s} {entry['norm']:7s} "
            f"ranking accuracy {own['auc']}  equal error rate {own['eer']}"
        )
    typer.echo(f"{report['pairs']} labeled pairs -> {out}")


@app.command()
def coverage(
    episode: Path,
    subtitle: Annotated[Path, typer.Option(help="ASS subtitles for this episode")],
    out: Annotated[Path, typer.Option(help="New check output folder")],
    pad: Annotated[
        float,
        typer.Option(help="Seconds to keep before and after each cut, so it is easier to hear"),
    ] = 0.0,
) -> None:
    """Find dialogue lines with no matching clip, and cut them into audio files for listening,
    grouped by reason."""
    from avs.evaluation.coverage import coverage as check

    report = check(episode, subtitle, out, pad)
    own = report["summary"]
    typer.echo(
        f"{report['episode']}: {own['dialogue_lines']} dialogue lines, "
        f"{own['lines_with_clip']} with a clip, {own['lines_without_clip']} without a clip "
        f"(shorter than {report['floor_seconds']} seconds: {own['below_floor']} lines; "
        f"long enough but no speech found: {own['no_speech_found']} lines)"
    )
    typer.echo(
        f"Gaps with no clip but with dialogue: {own['holes']}, "
        f"{own['hole_seconds'] / 60:.1f} minutes in total, "
        f"containing {own['hole_dialogue_seconds']:.0f} seconds of dialogue"
    )
    typer.echo(f"Offset {report['offset_seconds']:+.2f} seconds; audio files and list -> {out}")


@app.command()
def export(groups: Path, out: Annotated[Path, typer.Option(help="New audio folder")]) -> None:
    """Export each identity group from the original-sample-rate vocal track, with no audio quality
    threshold."""
    result = pipeline.export_groups(groups, out)
    typer.echo(f"Exported {result['files']} clips, {result['total_sec']} seconds in total -> {out}")


@app.command()
def label(
    episode: Path,
    archive: Annotated[Path, typer.Option(help="Human archive, for example annotations/ep03.json")],
    count: int = 50,
    port: int = 8765,
    plan: Annotated[
        Path | None,
        typer.Option(
            help="Labeling plan; if given, only the clips in the plan are labeled, and --count is "
            "ignored"
        ),
    ] = None,
    known: Annotated[
        list[Path] | None,
        typer.Option(
            help="Existing archives used for the page's name list, can be given more than once; by "
            "default, the ones recorded in the plan"
        ),
    ] = None,
    every: Annotated[
        bool,
        typer.Option(
            "--all", help="Label all clips of this episode, in time order; --count is ignored"
        ),
    ] = False,
    video: Annotated[
        Path | None,
        typer.Option(
            help="Video of this episode; if given, the matching picture is shown on the page and "
            "cut on demand"
        ),
    ] = None,
) -> None:
    """Sample clips, or take them from the plan or the whole episode, check the picture to label
    each character name, and save each one to the archive."""
    from avs.labeling import run

    run(episode, archive, count, port, plan, known, every, video)


@app.command()
def label_plan(
    candidate: Annotated[
        Path, typer.Option(help="Candidate grouping, for example one made in two steps")
    ],
    baseline: Annotated[
        Path, typer.Option(help="Current default grouping, used to mark clips assigned differently")
    ],
    annotation: Annotated[
        list[Path], typer.Option(help="Existing human archives, can be given more than once")
    ],
    out: Annotated[Path, typer.Option(help="New labeling plan JSON")],
) -> None:
    """List the unlabeled short clips that the candidate attaches to more than one group. These form
    the scope for the next labeling round."""
    from avs.labeling import build_plan

    plan = build_plan(candidate, baseline, annotation, out)
    for episode, own in plan["summary"].items():
        typer.echo(
            f"{episode}: {own['clips']} clips waiting to be labeled, "
            f"of which {own['moved']} are assigned to different groups in the two groupings"
        )
    typer.echo(f"Plan -> {out}")
