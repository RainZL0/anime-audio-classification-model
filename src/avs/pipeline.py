"""Subtitle clips, the voiceprint cache, identity grouping and export are independent of each other.
Changing the grouping does not run the audio models."""

from __future__ import annotations

import math
import re
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from avs.embeddings.extract import ANIME_VA, FRONTIER, MIN_SECONDS, embed_segments
from avs.project import (
    cache_dir,
    cache_signature,
    digest,
    load_episode,
    read_json,
    resolve_device,
    segment_rows,
    time_key,
    validate_name,
    write_json,
)

TOKEN_HOWTO = (
    "Accept the terms of use at https://huggingface.co/pyannote/speaker-diarization-community-1, "
    "then log in by running uv run hf auth login"
)
NO_TOKEN_HINT = (
    "--offset was not given, so pyannote would have to measure the subtitle offset automatically, "
    "but this machine has no Hugging Face token. "
    "Choose one: give --offset (it is the same for all episodes from the same source and subtitle "
    "group, so enter the value measured for an earlier episode), or " + TOKEN_HOWTO
)


def has_hf_token() -> bool:
    from huggingface_hub import get_token

    return get_token() is not None


def prepare(
    video: Path,
    subtitles: Path,
    out: Path,
    name: str,
    vocals: Path | None = None,
    offset: float | None = None,
    device: str = "auto",
    audio: Path | None = None,
) -> dict[str, Any]:
    """Each subtitle line is a clip. The offset can be given directly, or measured automatically if
    it is not given.

    **The video and the subtitles are both required.** The subtitles decide how clips are cut. The
    video is the main evidence for identifying speakers while labeling. The audio is taken from the
    video by default. If `audio` is given separately, its duration must match the video, otherwise
    it is probably not the same source.

    **Speech detection is only used to measure the offset. It does not decide whether anyone is
    speaking inside a clip.** The early approach used the detection results, intersected them with
    the subtitles, and then cut. That threw away 40% of the dialogue lines, so it has been
    abandoned. When `--offset` is given, detection is not run at all. The offset is stable for the
    same source and subtitle group (measured on episodes 1 to 3: -0.95, -0.96, -0.96), so simply
    give the value measured for the previous episode, then check coverage with `avs coverage` to
    make sure it is complete.
    """
    from avs.audio import audio_info, diarize, extract_audio, make_analysis_copy, separate_vocals
    from avs.stages.subtitle import MIN_OVERLAP_RATIO, find_offset, load_lines

    validate_name(name)
    if out.exists():
        raise ValueError(f"Output folder already exists: {out}")
    if offset is not None and not math.isfinite(offset):
        raise ValueError("The subtitle offset must be a finite number")
    if not video.is_file():
        raise ValueError(f"Video does not exist: {video}")
    if not subtitles.is_file():
        raise ValueError(f"Subtitles do not exist: {subtitles}")
    lines = load_lines(subtitles)
    if not lines:
        raise ValueError("There are no dialogue lines in the subtitles")
    if offset is None and not has_hf_token():
        raise ValueError(NO_TOKEN_HINT)
    device = resolve_device(device)
    picture = video_seconds(video)
    if audio is not None and abs(audio_info(audio).duration - picture) > VIDEO_TOLERANCE:
        raise ValueError(
            "The audio track and the video have different durations, so they are probably not the "
            "same source"
        )
    out.mkdir(parents=True)
    if audio is None:
        audio = out / "source.flac"
        extract_audio(video, audio)
    source = audio_info(audio)
    if source.sample_rate < 32000:
        raise ValueError("The original audio track has a sample rate below 32000 Hz")
    if vocals:
        info = audio_info(vocals)
        if info.sample_rate != source.sample_rate or abs(info.duration - source.duration) > 0.1:
            raise ValueError(
                "The sample rate or duration of the reused vocal track does not match the original "
                "audio track"
            )
    if vocals is None:
        # Half precision is only faster on the GPU, so use full precision on the CPU.
        precision = "fp16" if device == "cuda" else "fp32"
        vocals = separate_vocals(
            audio, out / "separated", Path("models"), source.sample_rate, precision=precision
        )
    analysis = out / "analysis_16k.wav"
    make_analysis_copy(vocals, analysis)
    overlap = None
    if offset is None:
        result = diarize(analysis, device)
        speech = [(s.start, s.end) for s in result.speaker_diarization.get_timeline().support()]
        offset, overlap = find_offset(lines, speech, source.duration)
        if overlap < MIN_OVERLAP_RATIO:
            raise ValueError(
                f"Subtitle alignment overlap {overlap} is too low. "
                "Check the subtitles against the source"
            )
    # Remove duplicate times from bilingual subtitles. Do not join adjacent lines, and do not shrink
    # the boundaries based on audio quality or speaker labels.
    spans = sorted({(max(0.0, a + offset), min(source.duration, b + offset)) for a, b in lines})
    rows = segment_rows(name, [{"start": a, "end": b} for a, b in spans if b > a])
    if not rows:
        raise ValueError("All subtitles fall outside the audio track")
    episode = {
        "schema": "avs.episode.v1",
        "name": name,
        "source": str(audio.resolve()),
        "video": str(video.resolve()),
        "vocals": str(vocals.resolve()),
        "analysis": str(analysis.resolve()),
        "subtitles": str(subtitles.resolve()),
        "subtitle_offset": offset,
        "alignment_overlap": overlap,
        "sample_rate": source.sample_rate,
        "segmentation": "subtitle_lines",
    }
    write_json(out / "segments.json", rows)
    write_json(out / "episode.json", episode)
    return {"episode": name, "segments": len(rows), "offset": offset, "overlap": overlap}


VIDEO_TOLERANCE = 0.5
"""The duration of the video and of the original audio can differ by at most this many seconds. If
they differ by more, it is almost certainly not the same source."""


def video_seconds(video: Path) -> float:
    import shutil
    import subprocess

    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe not found. It is installed together with ffmpeg")
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ValueError(f"Cannot read the video duration: {video}") from exc


def attach_video(directory: Path, video: Path) -> dict[str, Any]:
    """Record the video for an episode. Pictures are the main evidence for identifying speakers
    during labeling, so the duration must match the audio track."""
    from avs.audio import audio_info

    episode, _ = load_episode(directory)
    if not video.is_file():
        raise ValueError(f"Video does not exist: {video}")
    seconds = video_seconds(video)
    audio = audio_info(Path(episode["source"])).duration
    if abs(seconds - audio) > VIDEO_TOLERANCE:
        raise ValueError(
            f"The video is {seconds:.2f} seconds and the audio is {audio:.2f} seconds. "
            "The difference is too large, so they are probably not the same source"
        )
    write_json(directory / "episode.json", {**episode, "video": str(video.resolve())})
    return {
        "episode": episode["name"],
        "video_seconds": round(seconds, 2),
        "audio_seconds": round(audio, 2),
    }


MIN_SUBTITLE_MATCH = 0.8
"""When subtitles are added afterwards, at least this many clips must find dialogue. Otherwise the
wrong subtitle file was probably used."""


def attach_subtitles(directory: Path, subtitles: Path) -> dict[str, Any]:
    """Add the subtitle path and offset to early episodes that did not record them.

    Clips cut from subtitle lines are the subtitle lines plus one fixed offset, so the offset does
    not need to be measured again: subtract each line's start from each clip's start, and the most
    common difference is the offset.
    Then count how many clips can find dialogue, and refuse if there are too few. Early clips cut by
    speech detection did not have subtitle-line boundaries, so finding their dialogue uses time
    overlap. See app/workspace.py.
    """
    from avs.app.workspace import text_for
    from avs.stages.subtitle import load_dialogue

    episode, rows = load_episode(directory)
    dialogue = load_dialogue(subtitles)
    if not dialogue:
        raise ValueError("There are no dialogue lines in the subtitles")
    starts = {round(r["start"], 2) for r in rows}
    votes: Counter[float] = Counter()
    for line in dialogue:
        for row_start in starts:
            gap = round(row_start - line["start"], 2)
            if abs(gap) <= 30:
                votes[gap] += 1
    offset = votes.most_common(1)[0][0]
    lines = [(d["start"] + offset, d["end"] + offset, d["text"]) for d in dialogue]
    begins = [line[0] for line in lines]
    matched = sum(bool(text_for(lines, begins, r["start"], r["end"])) for r in rows) / len(rows)
    if matched < MIN_SUBTITLE_MATCH:
        raise ValueError(
            f"Only {matched:.0%} of clips can find dialogue, "
            "so this is probably not the subtitle for this episode"
        )
    write_json(
        directory / "episode.json",
        {**episode, "subtitles": str(subtitles.resolve()), "subtitle_offset": offset},
    )
    return {"episode": episode["name"], "offset": offset, "matched": round(matched, 4)}


def attach_text_subtitles(directory: Path, subtitles: Path) -> dict[str, Any]:
    """给一集另配一份字幕，导出时台词文字从它取，见 stages/text_subtitle.py。

    偏移拿它和切片段的那份字幕比出来。两道检查，过不了就拒绝、不写进 episode.json：
    对上之后的重合度不到 `MIN_AGREEMENT`；或者不到 `MIN_MATCHED` 的片段碰得到台词。
    """
    from avs.app.workspace import subtitle_lines
    from avs.stages.text_subtitle import (
        MIN_AGREEMENT,
        MIN_MATCHED,
        load_text_lines,
        measure_offset,
        shifted,
        touching,
    )

    episode, rows = load_episode(directory)
    if not subtitles.is_file():
        raise ValueError(f"字幕不存在：{subtitles}")
    cut = [(start, end) for start, end, _ in subtitle_lines(episode)]
    if not cut:
        raise ValueError(f"{episode['name']} 还没记切片段用的字幕，先用 avs set-subtitles 补上")
    lines = load_text_lines(subtitles)
    if not lines:
        raise ValueError(f"{subtitles.name} 里没有台词")
    offset, agreement = measure_offset(lines, cut)
    if agreement < MIN_AGREEMENT:
        raise ValueError(
            f"{subtitles.name} 和这一集切片段用的字幕最多只重合 {agreement:.0%}，"
            f"不到 {MIN_AGREEMENT:.0%}，多半不是这一集的字幕"
        )
    moved = shifted(lines, offset)
    matched = sum(bool(touching(moved, r["start"], r["end"])) for r in rows) / len(rows)
    if matched < MIN_MATCHED:
        raise ValueError(f"只有 {matched:.0%} 的片段碰得到 {subtitles.name} 的台词")
    result = {
        "text_subtitles": str(subtitles.resolve()),
        "text_subtitle_offset": offset,
        "text_subtitle_agreement": agreement,
    }
    write_json(directory / "episode.json", {**episode, **result})
    return {"episode": episode["name"], **result, "matched": round(matched, 4)}


def next_episode_name(workspace: Path) -> str:
    """The next unused `epNN` in the workspace."""
    folder = workspace / "episodes"
    names = [p.name for p in folder.iterdir()] if folder.is_dir() else []
    numbers = [int(m.group(1)) for n in names if (m := re.fullmatch(r"ep(\d+)", n))]
    return f"ep{max(numbers, default=0) + 1:02d}"


def find_episode_by_video(workspace: Path, video: Path) -> str | None:
    """The episode in the workspace that was already processed with this video; None if there is
    none."""
    from avs.app.workspace import episode_dirs

    wanted = str(video.resolve())
    for directory in episode_dirs(workspace):
        episode = read_json(directory / "episode.json")
        if episode.get("video") == wanted:
            return str(episode["name"])
    return None


def add_episode(
    workspace: Path,
    video: Path,
    subtitles: Path,
    name: str | None = None,
    text_subtitles: Path | None = None,
    audio: Path | None = None,
    offset: float | None = None,
    device: str = "auto",
    say: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """One command adds one episode: `prepare`, the few voiceprints the interface needs, and, if
    there are Japanese subtitles, attaches them too.

    If it fails partway, the steps already done are kept, and running the same command again
    continues from where it stopped: `prepare` counts as done once it writes episode.json, and
    voiceprints are cached.
    If `prepare` itself fails, the half-built folder is deleted, so the next run is not blocked by
    "output folder already exists". If no episode name is given, first look for an episode already
    processed with the same video. If none is found, take the next `epNN`.
    """
    from avs.app.workspace import DEFAULT_MODELS, GROUPING_MODEL

    if name is None:
        name = find_episode_by_video(workspace, video) or next_episode_name(workspace)
    validate_name(name)
    out = workspace / "episodes" / name
    device = resolve_device(device)
    say(f"{name}: computing on {device}, folder {out}")

    if (out / "episode.json").exists():
        episode, rows = load_episode(out)
        if episode.get("video") != str(video.resolve()):
            raise ValueError(
                f"{name} was already processed with another video: {episode.get('video')}"
            )
        say(f"Already cut {len(rows)} clips, continuing from here")
    else:
        if out.exists():
            raise ValueError(
                f"{out} already exists but is not a finished episode. "
                "Make sure it is not in use, delete it, and try again"
            )
        say(
            "Extracting audio, separating vocals, cutting clips by subtitles (this step is the "
            "slowest)"
        )
        try:
            result = prepare(video, subtitles, out, name, None, offset, device, audio)
        except BaseException:
            if out.exists():
                shutil.rmtree(out)
            raise
        say(f"Cut {result['segments']} clips, subtitle offset {result['offset']:+.2f} seconds")

    models = list(dict.fromkeys((*DEFAULT_MODELS, GROUPING_MODEL)))
    for model in models:
        say(f"Computing voiceprints: {model}")
        embed(out, model, device)

    if text_subtitles is not None:
        say("Attaching text subtitles")
        own = attach_text_subtitles(out, text_subtitles)
        say(
            f"Offset {own['text_subtitle_offset']:+.2f} seconds, "
            f"{own['matched']:.1%} of clips match dialogue"
        )

    _, rows = load_episode(out)
    return {"episode": name, "directory": str(out), "segments": len(rows), "models": models}


def extend_segments(directory: Path, subtitle: Path, floor: float = MIN_SECONDS) -> dict[str, Any]:
    """Add the dialogue lines that have no matching clip in the subtitles to this episode's clip
    table. Existing clips are not touched at all.

    Clip IDs are a hash of the episode name and time range, independent of neighbouring clips. So if
    the change only adds clips, existing labels and archives still line up, and nothing needs
    relabeling.
    The cost is that the voiceprint cache becomes stale, so `embed` has to be run again.

    The added lines will certainly include narration, crowd cheers and other sounds that do not
    belong to any character. Do not guess here. Add them all and let the human ear decide. Label
    them "other" during labeling.
    """
    from avs.audio import audio_info
    from avs.evaluation.coverage import align_to_segments, uncovered_lines
    from avs.stages.subtitle import load_dialogue

    episode, rows = load_episode(directory)
    lines = load_dialogue(subtitle)
    if not lines:
        raise ValueError(f"{subtitle} has no dialogue lines. Check the subtitle style names")
    offset, inside = align_to_segments(lines, rows)
    if inside < len(rows) * 0.9:
        raise ValueError(
            f"Only {inside}/{len(rows)} clips fall inside subtitle lines, "
            "so this subtitle is probably not for this episode"
        )

    duration = audio_info(Path(episode["vocals"])).duration
    missing = uncovered_lines(lines, rows, offset)
    added, too_short = [], 0
    for entry in missing:
        start, end = max(0.0, entry["start"]), min(duration, entry["end"])
        if end - start < floor:
            too_short += 1
            continue
        added.append({"start": start, "end": end})
    if not added:
        raise ValueError("No dialogue lines can be added. The clip table was not changed")

    spans = [{"start": r["start"], "end": r["end"]} for r in rows] + added
    combined = segment_rows(episode["name"], spans)
    kept = {r["id"] for r in rows}
    if not kept <= {r["id"] for r in combined}:
        raise ValueError("Adding clips changed existing clips, so the operation was stopped")
    write_json(directory / "segments.json", combined)
    return {
        "episode": episode["name"],
        "before": len(rows),
        "after": len(combined),
        "added": len(added),
        "too_short": too_short,
        "floor_seconds": floor,
        "offset_seconds": offset,
        "shortest_added": round(min(a["end"] - a["start"] for a in added), 3),
    }


def embed(
    directory: Path, model: str = FRONTIER, device: str = "auto", window: float = 0.0
) -> dict[str, Any]:
    """Voiceprints are bound to their input. If a complete cache already exists, it is reused
    directly. Short clips stay in the clip table."""
    import numpy as np

    validate_name(model)
    episode, rows = load_episode(directory)
    signature = cache_signature(directory, model, window)
    cache = cache_dir(directory, model, window)
    if (cache / "cache.json").exists() and read_json(cache / "cache.json") == signature:
        cached_records, _ = load_embeddings(directory, model, window)
        return {"episode": episode["name"], "embedded": len(cached_records), "cached": True}
    eligible = [dict(r, speaker="") for r in rows if r["end"] - r["start"] >= MIN_SECONDS]
    if eligible:
        metadata, vectors = embed_segments(
            Path(episode["analysis"]), eligible, model, resolve_device(device), window
        )
        by_time = {time_key(r): r for r in rows}
        records = [by_time[(round(m.start, 3), round(m.end, 3))] for m in metadata]
    else:
        records, vectors = [], np.empty((0, 0), dtype=np.float32)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(cache / "vectors.npy", vectors)
    write_json(cache / "metadata.json", records)
    write_json(cache / "cache.json", signature)
    return {"episode": episode["name"], "embedded": len(records), "cached": False}


def load_embeddings(
    directory: Path, model: str, window: float = 0.0
) -> tuple[list[dict[str, Any]], Any]:
    import numpy as np

    validate_name(model)
    cache = cache_dir(directory, model, window)
    if read_json(cache / "cache.json") != cache_signature(directory, model, window):
        raise ValueError(f"{directory} voiceprint cache is out of date. Run embed again")
    records = read_json(cache / "metadata.json")
    vectors = np.load(cache / "vectors.npy", allow_pickle=False)
    _, rows = load_episode(directory)
    by_id = {r["id"]: r for r in rows}
    if (
        vectors.ndim != 2
        or len(vectors) != len(records)
        or not np.isfinite(vectors).all()
        or len({r["id"] for r in records}) != len(records)
        or any(by_id.get(r["id"]) != r for r in records)
    ):
        raise ValueError("The voiceprint matrix does not match the clip information")
    if len(vectors) and not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError("The voiceprints are not unit-length vectors")
    return records, vectors


def relative_threshold(directories: list[Path], model: str = ANIME_VA) -> float:
    """Compute the threshold from the pool made of these episodes, using the pool's own distances.
    See pool_threshold in stages/cluster.py."""
    import numpy as np

    from avs.stages.cluster import POOL_MULTIPLIERS, pool_threshold

    if model not in POOL_MULTIPLIERS:
        raise ValueError(
            f"{model} has no multiplier for setting the threshold from the pool yet. "
            "First measure one with avs drift"
        )
    matrices = [load_embeddings(directory, model)[1] for directory in directories]
    vectors = np.concatenate([m for m in matrices if len(m)]) if matrices else np.empty((0, 0))
    return pool_threshold(vectors, POOL_MULTIPLIERS[model])


def group(
    directories: list[Path],
    out: Path,
    threshold: float = 0.5,
    model: str = ANIME_VA,
    method: str = "average",
) -> dict[str, Any]:
    import numpy as np

    from avs.stages.cluster import METHODS, cluster

    if method not in METHODS:
        raise ValueError(f"Linking rule must be one of {', '.join(METHODS)}, got {method}")

    if out.exists():
        raise ValueError(
            f"Output already exists. Use a new file to keep the previous grouping: {out}"
        )
    if not directories or len({p.resolve() for p in directories}) != len(directories):
        raise ValueError("At least one episode folder is required, and no folder may be repeated")
    if not math.isfinite(threshold) or not 0 < threshold <= 2:
        raise ValueError("The distance threshold must be between 0 and 2")
    episodes = {}
    all_rows = []
    records = []
    matrices = []
    for directory in directories:
        episode, rows = load_episode(directory)
        if episode["name"] in episodes:
            raise ValueError("Episode names are duplicated. Give each episode a different name")
        own_records, vectors = load_embeddings(directory, model)
        episodes[episode["name"]] = {
            **episode,
            "directory": str(directory.resolve()),
            "segments_sha256": digest(directory / "segments.json"),
        }
        all_rows.extend(rows)
        records.extend(own_records)
        if len(vectors):
            matrices.append(vectors)
    vectors = np.concatenate(matrices) if matrices else np.empty((0, 0))
    labels = cluster(vectors, threshold, method, [r["end"] - r["start"] for r in records])
    # Number groups in the order their clips first appear. Small groups are kept; they are not
    # merged into a miscellaneous bucket.
    numbers: dict[int, str] = {}
    by_id = {}
    for row, label in zip(records, labels, strict=True):
        number = numbers.setdefault(int(label), f"speaker_{len(numbers) + 1:03d}")
        by_id[row["id"]] = number
    assignments = [dict(r, speaker=by_id.get(r["id"])) for r in all_rows]
    counts = Counter(r["speaker"] for r in assignments if r["speaker"] is not None)
    result = {
        "schema": "avs.groups.v1",
        "model": model,
        "threshold": threshold,
        "strategy": f"global_{method}",
        "audio_assumption": "single_speaker",
        "episodes": episodes,
        "assignments": assignments,
        "summary": {
            "clips": len(assignments),
            "groups": len(counts),
            "singleton_groups": sum(n == 1 for n in counts.values()),
            "unassigned": sum(r["speaker"] is None for r in assignments),
        },
    }
    write_json(out, result)
    return result


def export_groups(groups_file: Path, out: Path) -> dict[str, Any]:
    from avs.stages.export import export, summarize, write_manifest

    data = read_json(groups_file)
    if data.get("schema") != "avs.groups.v1":
        raise ValueError("Please provide a grouping file produced by the current group command")
    if out.exists():
        raise ValueError(f"Export folder already exists. Please use a new folder: {out}")
    assigned: dict[str, list[Any]] = {}
    for row in data["assignments"]:
        name = row["speaker"] or "_unassigned"
        validate_name(name) if row["speaker"] else None
        validate_name(row["episode"])
        assigned.setdefault(name, []).append(SimpleNamespace(**row))
    vocals = {name: Path(e["vocals"]) for name, e in data["episodes"].items()}
    written = export(assigned, vocals, out)
    write_manifest(written, out)
    write_json(out / "groups.json", data)
    return summarize(written)
