"""Add an episode: cut clips by subtitles, attach the video and text subtitles, and compute and
cache the voiceprints."""

from __future__ import annotations

import math
import re
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from avoc.embeddings.extract import FRONTIER, MIN_SECONDS, embed_segments
from avoc.language import Words, say
from avoc.project import (
    cache_dir,
    cache_signature,
    load_episode,
    read_json,
    resolve_device,
    segment_rows,
    time_key,
    validate_name,
    write_json,
)
from avoc.stages.captions import marked_note
from avoc.stages.text_language import name_of

TOKEN_PAGE = "https://huggingface.co/pyannote/speaker-diarization-community-1"
TOKEN_HOWTO = Words(
    f"先在 {TOKEN_PAGE} 同意使用条款，再运行 uv run hf auth login 登录",
    f"Accept the terms of use at {TOKEN_PAGE}, then log in by running uv run hf auth login",
)
NO_TOKEN_HINT = Words(
    "没给字幕偏移，要用 pyannote 自动测，但这台机器没有 Hugging Face 令牌。"
    "二选一：填上偏移（同一个片源、同一个字幕组的每一集都一样，填前面测过的值就行），或者"
    + TOKEN_HOWTO.zh,
    "--offset was not given, so pyannote would have to measure the subtitle offset automatically, "
    "but this machine has no Hugging Face token. "
    "Choose one: give --offset (it is the same for all episodes from the same source and subtitle "
    "group, so enter the value measured for an earlier episode), or " + TOKEN_HOWTO.en,
)

PROGRESS_MARK = "\x1f"
"""Put in front of each progress line of `avoc add` when the interface runs it (environment
variable `AVOC_MARK_PROGRESS`). Some libraries print warnings to the same output, and the interface
shows only the marked lines as progress. The character is invisible."""


def has_hf_token() -> bool:
    from huggingface_hub import get_token

    return get_token() is not None


def check_language(code: str) -> str:
    from avoc.stages.text_language import LANGUAGES

    if code not in LANGUAGES:
        raise ValueError(
            say(
                f"不认识的语言 {code}，可以用：{', '.join(LANGUAGES)}",
                f"unknown language {code}; use one of: {', '.join(LANGUAGES)}",
            )
        )
    return code


def choose_track(tracks: list[Any], spoken: str | None) -> tuple[int, str, str]:
    """Which audio track to cut from, the language spoken in it, and where that came from:
    `person` (given), `track` (its language tag) or `assumed`.

    With a language given, the first track tagged with it. Without, a Japanese track if there is
    one (the original voices of anime), else the track marked default, else the first."""
    from avoc.stages.text_language import ASSUMED, from_tag

    wanted = spoken or ASSUMED
    tagged = [t for t in tracks if from_tag(t.tag) == wanted]
    default = [t for t in tracks if t.default]
    track = (tagged or default or tracks)[0]
    if spoken:
        return track.number, spoken, "person"
    found = from_tag(track.tag)
    return track.number, found or ASSUMED, "track" if found else "assumed"


def track_note(tracks: list[Any], number: int, spoken: str, how: str) -> str:
    """One line for the person: which track the voices come from and what language it speaks."""
    from avoc.stages.text_language import from_tag

    def described(track: Any) -> str:
        code = from_tag(track.tag)
        what = name_of(code) if code else (track.tag or say("没标语言", "no language tag"))
        return f"{track.number + 1} ({what}{', ' + track.title if track.title else ''})"

    used = tracks[number]
    line = say(
        f"用第 {described(used)} 条音轨，共 {len(tracks)} 条；说的是{name_of(spoken)}",
        f"Using audio track {described(used)} of {len(tracks)}; spoken language: {name_of(spoken)}",
    )
    if how == "assumed":
        line += say(
            "（音轨没标语言，按日语算；不对就加 --spoken）",
            " (the track has no language tag, so Japanese is assumed; if wrong, give --spoken)",
        )
    elif how == "person" and from_tag(used.tag) not in (None, spoken):
        line += say(
            f"。没有标成{name_of(spoken)}的音轨，先用这一条",
            f". No track is tagged {name_of(spoken)}, so this one is used",
        )
    others = [described(t) for t in tracks if t.number != number]
    if others:
        line += say(
            f"。其他音轨：{', '.join(others)}；要换就用 --spoken",
            f". Other tracks: {', '.join(others)}; to use another, give --spoken",
        )
    return line


def prepare(
    video: Path,
    subtitles: Path,
    out: Path,
    name: str,
    vocals: Path | None = None,
    offset: float | None = None,
    device: str = "auto",
    audio: Path | None = None,
    styles: list[str] | None = None,
    spoken: str | None = None,
) -> dict[str, Any]:
    """Each subtitle line is a clip. The offset can be given directly, or measured automatically if
    it is not given. `styles` are the subtitle styles that hold the dialogue; if None, they are
    picked automatically (see `stages/subtitle.py`). The styles used are kept in episode.json, so
    the interface reads the same lines later.

    `spoken` is the language spoken; None takes it from the audio track (see `choose_track`). The
    voices are taken from the track in that language. It is kept in episode.json, and exported text
    must be in it.

    **The video and the subtitles are both required.** The subtitles decide how clips are cut. The
    video is the main evidence for identifying speakers while labeling. The audio is taken from the
    video by default. If `audio` is given separately, its duration must match the video, otherwise
    it is probably not the same source.

    **Speech detection is only used to measure the offset. It does not decide whether anyone is
    speaking inside a clip.** The early approach used the detection results, intersected them with
    the subtitles, and then cut. That threw away 40% of the dialogue lines, so it has been
    abandoned. When `--offset` is given, detection is not run at all. The offset is stable for the
    same source and subtitle group (measured on episodes 1 to 3: -0.95, -0.96, -0.96), so simply
    give the value measured for the previous episode.
    """
    from avoc.audio import (
        audio_info,
        audio_tracks,
        diarize,
        extract_audio,
        make_analysis_copy,
        separate_vocals,
    )
    from avoc.stages.subtitle import (
        MIN_OVERLAP_RATIO,
        find_offset,
        load_lines,
        pick_styles,
        read_subtitles,
    )
    from avoc.stages.text_language import ASSUMED

    validate_name(name)
    if out.exists():
        raise ValueError(say(f"输出文件夹已经存在：{out}", f"Output folder already exists: {out}"))
    if offset is not None and not math.isfinite(offset):
        raise ValueError(
            say("字幕偏移必须是一个有限的数", "The subtitle offset must be a finite number")
        )
    if not video.is_file():
        raise ValueError(say(f"视频不存在：{video}", f"Video does not exist: {video}"))
    if not subtitles.is_file():
        raise ValueError(say(f"字幕不存在：{subtitles}", f"Subtitles do not exist: {subtitles}"))
    if styles is None:
        styles = pick_styles(read_subtitles(subtitles))
    lines = load_lines(subtitles, styles)
    if not lines:
        raise ValueError(say("字幕里没有台词", "There are no dialogue lines in the subtitles"))
    if offset is None and not has_hf_token():
        raise ValueError(str(NO_TOKEN_HINT))
    if spoken is not None:
        check_language(spoken)
    track, how = None, "person" if spoken else "assumed"
    if audio is None:
        tracks = audio_tracks(video)
        if not tracks:
            raise ValueError(
                say(f"视频里没有音轨：{video}", f"the video has no audio track: {video}")
            )
        track, spoken, how = choose_track(tracks, spoken)
    spoken = spoken or ASSUMED
    device = resolve_device(device)
    picture = video_seconds(video)
    if audio is not None and abs(audio_info(audio).duration - picture) > VIDEO_TOLERANCE:
        raise ValueError(
            say(
                "音轨和视频的时长不一样，多半不是同一个片源",
                "The audio track and the video have different durations, so they are probably not "
                "the same source",
            )
        )
    out.mkdir(parents=True)
    if audio is None:
        audio = out / "source.flac"
        extract_audio(video, audio, track or 0)
    source = audio_info(audio)
    if source.sample_rate < 32000:
        raise ValueError(
            say(
                "原音轨的采样率低于 32000 Hz",
                "The original audio track has a sample rate below 32000 Hz",
            )
        )
    if vocals:
        info = audio_info(vocals)
        if info.sample_rate != source.sample_rate or abs(info.duration - source.duration) > 0.1:
            raise ValueError(
                say(
                    "复用的人声轨和原音轨的采样率或时长对不上",
                    "The sample rate or duration of the reused vocal track does not match the "
                    "original audio track",
                )
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
                say(
                    f"字幕和声音只重合 {overlap}，太低了。检查字幕和片源是不是对得上",
                    f"Subtitle alignment overlap {overlap} is too low. "
                    "Check the subtitles against the source",
                )
            )
    # Remove duplicate times from bilingual subtitles. Do not join adjacent lines, and do not shrink
    # the boundaries based on audio quality or speaker labels.
    spans = sorted({(max(0.0, a + offset), min(source.duration, b + offset)) for a, b in lines})
    rows = segment_rows(name, [{"start": a, "end": b} for a, b in spans if b > a])
    if not rows:
        raise ValueError(say("字幕全都落在音轨外面", "All subtitles fall outside the audio track"))
    episode = {
        "schema": "episode.v1",
        "name": name,
        "source": str(audio.resolve()),
        "video": str(video.resolve()),
        "vocals": str(vocals.resolve()),
        "analysis": str(analysis.resolve()),
        "subtitles": str(subtitles.resolve()),
        "subtitle_styles": styles,
        "subtitle_offset": offset,
        "alignment_overlap": overlap,
        "sample_rate": source.sample_rate,
        "segmentation": "subtitle_lines",
        "audio_track": track,
        "spoken_language": spoken,
        "spoken_from": how,
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
    from avoc.audio import audio_info

    episode, _ = load_episode(directory)
    if not video.is_file():
        raise ValueError(say(f"视频不存在：{video}", f"Video does not exist: {video}"))
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
    from avoc.app.workspace import text_for
    from avoc.stages.subtitle import load_dialogue, pick_styles, read_subtitles

    episode, rows = load_episode(directory)
    styles = pick_styles(read_subtitles(subtitles))
    dialogue = load_dialogue(subtitles, styles)
    if not dialogue:
        raise ValueError(say("字幕里没有台词", "There are no dialogue lines in the subtitles"))
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
        {
            **episode,
            "subtitles": str(subtitles.resolve()),
            "subtitle_styles": styles,
            "subtitle_offset": offset,
        },
    )
    return {"episode": episode["name"], "offset": offset, "matched": round(matched, 4)}


def attach_text_subtitles(directory: Path, subtitles: Path) -> dict[str, Any]:
    """Attach a second subtitle file to an episode, in the language spoken. The text for export is
    taken from it; see stages/text_subtitle.py. Only its lines in that language are used, so a
    bilingual file works too.

    The time offset is found by comparing it with the subtitles used for cutting. The file is
    refused and not written to episode.json when it has no lines in the spoken language, when after
    lining up the overlap is below `MIN_AGREEMENT`, or when fewer than `MIN_MATCHED` of the clips
    touch a line.
    """
    from avoc.app.workspace import subtitle_lines
    from avoc.stages.captions import marked
    from avoc.stages.text_subtitle import (
        MIN_AGREEMENT,
        MIN_MATCHED,
        load_text_lines,
        measure_offset,
        shifted,
        touching,
    )

    episode, rows = load_episode(directory)
    if not subtitles.is_file():
        raise ValueError(say(f"字幕不存在：{subtitles}", f"subtitles not found: {subtitles}"))
    cut = [(start, end) for start, end, _ in subtitle_lines(episode)]
    if not cut:
        raise ValueError(
            say(
                f"{episode['name']} 还没记切片段用的字幕，先用 avoc set-subtitles 补上",
                f"{episode['name']} has no subtitles recorded for cutting; "
                "add them with avoc set-subtitles",
            )
        )
    spoken = spoken_language(episode)
    check_text_language(subtitles, spoken)
    lines = load_text_lines(subtitles, spoken=spoken)
    if not lines:
        raise ValueError(say(f"{subtitles.name} 里没有台词", f"{subtitles.name} has no lines"))
    offset, agreement = measure_offset(lines, cut)
    if agreement < MIN_AGREEMENT:
        raise ValueError(
            say(
                f"{subtitles.name} 和这一集切片段用的字幕最多只重合 {agreement:.0%}，"
                f"不到 {MIN_AGREEMENT:.0%}，多半不是这一集的字幕。"
                "也可能是另一个版本的视频配的字幕（帧率不同，或者删减过），那样时间会越差越多",
                f"{subtitles.name} overlaps this episode's subtitles by at most {agreement:.0%}, "
                f"below {MIN_AGREEMENT:.0%}; it is probably for another episode. It may also be "
                "made for another version of the video (another frame rate, or cut scenes), "
                "whose times drift apart",
            )
        )
    moved = shifted(lines, offset)
    matched = sum(bool(touching(moved, r["start"], r["end"])) for r in rows) / len(rows)
    if matched < MIN_MATCHED:
        raise ValueError(
            say(
                f"只有 {matched:.0%} 的片段碰得到 {subtitles.name} 的台词",
                f"only {matched:.0%} of the clips touch a line in {subtitles.name}",
            )
        )
    result = {
        "text_subtitles": str(subtitles.resolve()),
        "text_subtitle_offset": offset,
        "text_subtitle_agreement": agreement,
        "text_subtitle_marked": marked(x.text for x in lines),
    }
    write_json(directory / "episode.json", {**episode, **result})
    return {"episode": episode["name"], **result, "matched": round(matched, 4)}


def check_text_language(subtitles: Path, spoken: str) -> None:
    """Refuse text subtitles that have no lines in the language spoken."""
    from avoc.stages.text_language import languages_note
    from avoc.stages.text_subtitle import subtitle_languages

    languages = subtitle_languages(subtitles)
    if spoken in languages:
        return
    raise ValueError(
        say(
            f"{subtitles.name} 是{languages_note(languages)}，这一集说的是{name_of(spoken)}。"
            f"换一个{name_of(spoken)}字幕；要是这一集其实说的不是{name_of(spoken)}，"
            "先改它说的语言（--spoken）",
            f"{subtitles.name} is in {languages_note(languages)}, but this episode speaks "
            f"{name_of(spoken)}. Choose {name_of(spoken)} subtitles; if the episode really "
            "speaks another language, set it first (--spoken)",
        )
    )


def missing_text_note(episode: dict[str, Any]) -> str | None:
    """A warning when the cutting subtitles are not in the language spoken and nothing else gives
    that text. None when they are."""
    from avoc.stages.text_language import languages_note
    from avoc.stages.text_subtitle import subtitle_languages

    spoken = spoken_language(episode)
    path = Path(episode.get("subtitles") or "")
    if episode.get("text_subtitles") or not path.is_file():
        return None
    languages = subtitle_languages(path, episode.get("subtitle_styles"))
    if spoken in languages:
        return None
    return say(
        f"注意：字幕是{languages_note(languages)}，这一集说的是{name_of(spoken)}。"
        f"导出 GPT-SoVITS 或 Style-Bert-VITS2 要有{name_of(spoken)}台词：用 --text-subs 配上"
        f"{name_of(spoken)}字幕，或者以后用 avoc set-text-subtitles、在界面的导出页配。"
        "只导出音频（RVC）不需要",
        f"Note: the subtitles are in {languages_note(languages)}, but this episode speaks "
        f"{name_of(spoken)}. Exporting for GPT-SoVITS or Style-Bert-VITS2 needs the "
        f"{name_of(spoken)} text: attach {name_of(spoken)} subtitles with --text-subs, or later "
        "with avoc set-text-subtitles or on the Export page. Audio-only export (RVC) does not "
        "need it",
    )


def spoken_language(episode: dict[str, Any]) -> str:
    """The language spoken in an episode. Episodes added before it was recorded are taken to be
    Japanese."""
    from avoc.stages.text_language import ASSUMED

    return str(episode.get("spoken_language") or ASSUMED)


def set_spoken_language(directory: Path, code: str) -> dict[str, Any]:
    """Correct the language an episode speaks, for a wrong or missing tag. The voices stay the ones
    already cut; to cut from another audio track, add the episode again with `--spoken`."""
    episode, _ = load_episode(directory)
    check_language(code)
    write_json(
        directory / "episode.json", {**episode, "spoken_language": code, "spoken_from": "person"}
    )
    return {"episode": episode["name"], "spoken_language": code}


def next_episode_name(workspace: Path) -> str:
    """The next unused `epNN` in the workspace."""
    folder = workspace / "episodes"
    names = [p.name for p in folder.iterdir()] if folder.is_dir() else []
    numbers = [int(m.group(1)) for n in names if (m := re.fullmatch(r"ep(\d+)", n))]
    return f"ep{max(numbers, default=0) + 1:02d}"


def find_episode_by_video(workspace: Path, video: Path) -> str | None:
    """The episode in the workspace that was already processed with this video; None if there is
    none."""
    from avoc.app.workspace import episode_dirs

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
    report: Callable[[str], None] = lambda _: None,
    styles: list[str] | None = None,
    spoken: str | None = None,
) -> dict[str, Any]:
    """One command adds one episode: `prepare`, the few voiceprints the interface needs, and, if
    there are text subtitles in the spoken language, attaches them too. `report` gets one line for
    each step. `styles` are the subtitle styles that hold the dialogue; None picks them
    automatically. `spoken` is the language spoken; None takes it from the audio track.

    When no subtitles in the spoken language are given, the episode is still added, with a
    warning: audio-only export does not need text, and the subtitles can be attached later.

    If it fails partway, the steps already done are kept, and running the same command again
    continues from where it stopped: `prepare` counts as done once it writes episode.json, and
    voiceprints are cached.
    If `prepare` itself fails, the half-built folder is deleted, so the next run is not blocked by
    "output folder already exists". If no episode name is given, first look for an episode already
    processed with the same video. If none is found, take the next `epNN`.
    """
    from avoc.app.workspace import DEFAULT_MODELS, GROUPING_MODEL

    if name is None:
        name = find_episode_by_video(workspace, video) or next_episode_name(workspace)
    validate_name(name)
    out = workspace / "episodes" / name
    device = resolve_device(device)
    report(
        say(
            f"{name}：用 {device} 计算，文件夹 {out}",
            f"{name}: computing on {device}, folder {out}",
        )
    )

    if spoken is not None:
        check_language(spoken)
    if (out / "episode.json").exists():
        episode, rows = load_episode(out)
        if episode.get("video") != str(video.resolve()):
            raise ValueError(
                say(
                    f"{name} 已经用另一个视频处理过：{episode.get('video')}",
                    f"{name} was already processed with another video: {episode.get('video')}",
                )
            )
        if spoken is not None and spoken != spoken_language(episode):
            raise ValueError(
                say(
                    f"{name} 已经按{name_of(spoken_language(episode))}切好了。只是标错了的话用 "
                    "avoc set-spoken-language 改；要换音轨就删掉这一集再加",
                    f"{name} was already cut as {name_of(spoken_language(episode))}. If only "
                    "the label is wrong, use avoc set-spoken-language; to use another audio "
                    "track, delete the episode and add it again",
                )
            )
        report(
            say(
                f"已经切好 {len(rows)} 个片段，从这里接着做",
                f"Already cut {len(rows)} clips, continuing from here",
            )
        )
    else:
        if out.exists():
            raise ValueError(
                say(
                    f"{out} 已经存在，但不是处理完的一集。确认没在用以后删掉它，再试一次",
                    f"{out} already exists but is not a finished episode. "
                    "Make sure it is not in use, delete it, and try again",
                )
            )
        planned = spoken
        # A missing file or FFmpeg is reported by `prepare`.
        if audio is None and video.is_file() and shutil.which("ffprobe"):
            from avoc.audio import audio_tracks

            if tracks := audio_tracks(video):
                number, planned, how = choose_track(tracks, spoken)
                report(track_note(tracks, number, planned, how))
        # Refuse text subtitles in the wrong language now, not after the slow steps.
        if text_subtitles is not None and text_subtitles.is_file():
            check_text_language(text_subtitles, planned or "ja")
        if subtitles.is_file():
            from avoc.stages.subtitle import marked_dialogue, styles_note

            report(styles_note(subtitles, styles))
            if found := marked_dialogue(subtitles, styles):
                report(marked_note(found))
        report(
            say(
                "提取音轨、分离人声、按字幕切片段（这一步最慢）",
                "Extracting audio, separating vocals, cutting clips by subtitles (this step is the "
                "slowest)",
            )
        )
        try:
            result = prepare(
                video, subtitles, out, name, None, offset, device, audio, styles, spoken
            )
        except BaseException:
            if out.exists():
                shutil.rmtree(out)
            raise
        report(
            say(
                f"切了 {result['segments']} 个片段，字幕偏移 {result['offset']:+.2f} 秒",
                f"Cut {result['segments']} clips, subtitle offset {result['offset']:+.2f} seconds",
            )
        )

    # The text subtitles are attached last. Note them down now, so a run that stops before then
    # still attaches them when it carries on, even without --text-subs.
    episode = read_json(out / "episode.json")
    if text_subtitles is None:
        pending = episode.get("pending_text_subtitles")
        text_subtitles = Path(pending) if pending else None
    elif episode.get("pending_text_subtitles") != str(text_subtitles.resolve()):
        episode["pending_text_subtitles"] = str(text_subtitles.resolve())
        write_json(out / "episode.json", episode)

    models = list(dict.fromkeys((*DEFAULT_MODELS, GROUPING_MODEL)))
    for model in models:
        report(say(f"计算声纹：{model}", f"Computing voiceprints: {model}"))
        embed(out, model, device)

    if text_subtitles is not None:
        report(say("配台词字幕", "Attaching text subtitles"))
        try:
            own = attach_text_subtitles(out, text_subtitles)
        finally:
            # Also when they are refused: the episode itself is finished, and they can be
            # attached again from the Export view or with set-text-subtitles.
            episode = read_json(out / "episode.json")
            episode.pop("pending_text_subtitles", None)
            write_json(out / "episode.json", episode)
        report(
            say(
                f"偏移 {own['text_subtitle_offset']:+.2f} 秒，"
                f"{own['matched']:.1%} 的片段对上了台词",
                f"Offset {own['text_subtitle_offset']:+.2f} seconds, "
                f"{own['matched']:.1%} of clips match dialogue",
            )
        )
        if own.get("text_subtitle_marked"):
            report(marked_note(own["text_subtitle_marked"]))
    elif note := missing_text_note(read_json(out / "episode.json")):
        report(note)

    _, rows = load_episode(out)
    return {"episode": name, "directory": str(out), "segments": len(rows), "models": models}


def embed(directory: Path, model: str = FRONTIER, device: str = "auto") -> dict[str, Any]:
    """Voiceprints are bound to their input. If a complete cache already exists, it is reused
    directly. Short clips stay in the clip table."""
    import numpy as np

    validate_name(model)
    episode, rows = load_episode(directory)
    signature = cache_signature(directory, model)
    cache = cache_dir(directory, model)
    if (cache / "cache.json").exists() and read_json(cache / "cache.json") == signature:
        cached_records, _ = load_embeddings(directory, model)
        return {"episode": episode["name"], "embedded": len(cached_records), "cached": True}
    eligible = [dict(r, speaker="") for r in rows if r["end"] - r["start"] >= MIN_SECONDS]
    if eligible:
        metadata, vectors = embed_segments(
            Path(episode["analysis"]), eligible, model, resolve_device(device)
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


def load_embeddings(directory: Path, model: str) -> tuple[list[dict[str, Any]], Any]:
    import numpy as np

    validate_name(model)
    cache = cache_dir(directory, model)
    if read_json(cache / "cache.json") != cache_signature(directory, model):
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
