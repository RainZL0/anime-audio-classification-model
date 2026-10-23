"""字幕片段、声纹缓存、身份分组和导出各自独立，调分组不跑音频模型。"""

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
    "在 https://huggingface.co/pyannote/speaker-diarization-community-1 接受使用条款，"
    "再运行 uv run hf auth login 登录"
)
NO_TOKEN_HINT = (
    "没给 --offset，要用 pyannote 自动量字幕偏移，但本机没有 Hugging Face 令牌。"
    "二选一：给 --offset（同一片源同一字幕组各集一样，填上一集量到的值）；或者" + TOKEN_HOWTO
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
    """片段就是字幕行本身。偏移可以直接给，不给就自动量。

    **视频和字幕都是必需的。** 字幕决定怎么切片段；视频是标注时认人的主要依据。音轨默认从
    视频里抽；另给 `audio` 时，它的时长必须和视频对得上，否则多半不是同一个片源。

    **语音检测只用来量偏移，不参与判断片段里有没有人在说话。** 早期的做法是拿检测结果去和
    字幕求重叠再切，那样丢掉了四成对白行，已经废弃。给了 `--offset` 就完全不跑检测；
    同一片源同一字幕组的偏移是稳定的（第 1 至 3 集实测 -0.95、-0.96、-0.96），直接给上一集
    量到的值即可，跑完用 `avs coverage` 核对覆盖是否完整。
    """
    from avs.audio import audio_info, diarize, extract_audio, make_analysis_copy, separate_vocals
    from avs.stages.subtitle import MIN_OVERLAP_RATIO, find_offset, load_lines

    validate_name(name)
    if out.exists():
        raise ValueError(f"输出目录已存在：{out}")
    if offset is not None and not math.isfinite(offset):
        raise ValueError("字幕偏移必须是有限数值")
    if not video.is_file():
        raise ValueError(f"视频不存在：{video}")
    if not subtitles.is_file():
        raise ValueError(f"字幕不存在：{subtitles}")
    lines = load_lines(subtitles)
    if not lines:
        raise ValueError("字幕中没有对白行")
    if offset is None and not has_hf_token():
        raise ValueError(NO_TOKEN_HINT)
    device = resolve_device(device)
    picture = video_seconds(video)
    if audio is not None and abs(audio_info(audio).duration - picture) > VIDEO_TOLERANCE:
        raise ValueError("音轨和视频的时长对不上，多半不是同一个片源")
    out.mkdir(parents=True)
    if audio is None:
        audio = out / "source.flac"
        extract_audio(video, audio)
    source = audio_info(audio)
    if source.sample_rate < 32000:
        raise ValueError("原始音轨采样率低于 32000 Hz")
    if vocals:
        info = audio_info(vocals)
        if info.sample_rate != source.sample_rate or abs(info.duration - source.duration) > 0.1:
            raise ValueError("复用人声轨的采样率或时长与原始音轨不一致")
    if vocals is None:
        # 半精度只在显卡上快，CPU 上用全精度。
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
            raise ValueError(f"字幕对齐重合度 {overlap} 太低，请核对字幕与片源")
    # 去重双语字幕的相同时间，不拼相邻台词，不按音质或说话人标签收缩边界。
    spans = sorted({(max(0.0, a + offset), min(source.duration, b + offset)) for a, b in lines})
    rows = segment_rows(name, [{"start": a, "end": b} for a, b in spans if b > a])
    if not rows:
        raise ValueError("字幕全部落在音轨之外")
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
"""视频和原始音轨的时长最多差这么多秒。差得更多，几乎肯定不是同一个片源。"""


def video_seconds(video: Path) -> float:
    import shutil
    import subprocess

    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("找不到 ffprobe，它和 ffmpeg 一起装")
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ValueError(f"读不出视频时长：{video}") from exc


def attach_video(directory: Path, video: Path) -> dict[str, Any]:
    """给一集记上视频。标注时画面是认人的主要依据，所以时长必须和音轨对得上。"""
    from avs.audio import audio_info

    episode, _ = load_episode(directory)
    if not video.is_file():
        raise ValueError(f"视频不存在：{video}")
    seconds = video_seconds(video)
    audio = audio_info(Path(episode["source"])).duration
    if abs(seconds - audio) > VIDEO_TOLERANCE:
        raise ValueError(f"视频 {seconds:.2f} 秒、音轨 {audio:.2f} 秒，差太多，多半不是同一个片源")
    write_json(directory / "episode.json", {**episode, "video": str(video.resolve())})
    return {
        "episode": episode["name"],
        "video_seconds": round(seconds, 2),
        "audio_seconds": round(audio, 2),
    }


MIN_SUBTITLE_MATCH = 0.8
"""补记字幕时，至少这么多片段要能找到台词，否则多半是拿错了字幕文件。"""


def attach_subtitles(directory: Path, subtitles: Path) -> dict[str, Any]:
    """给早期没记字幕的集补上字幕路径和偏移。

    按字幕行切的片段就是字幕行加上一个固定偏移，所以偏移不用重新量：把每个片段开头减去
    每行字幕开头，出现最多的那个差就是偏移。再数一遍有多少片段能找到台词，太少就拒绝。
    早期按语音检测切的片段边界不是字幕行，所以找台词按时间重叠算，见 app/workspace.py。
    """
    from avs.app.workspace import text_for
    from avs.stages.subtitle import load_dialogue

    episode, rows = load_episode(directory)
    dialogue = load_dialogue(subtitles)
    if not dialogue:
        raise ValueError("字幕中没有对白行")
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
        raise ValueError(f"只有 {matched:.0%} 的片段找得到台词，多半不是这一集的字幕")
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
    from avs.language import say
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
        raise ValueError(say(f"字幕不存在：{subtitles}", f"subtitles not found: {subtitles}"))
    cut = [(start, end) for start, end, _ in subtitle_lines(episode)]
    if not cut:
        raise ValueError(
            say(
                f"{episode['name']} 还没记切片段用的字幕，先用 avs set-subtitles 补上",
                f"{episode['name']} has no subtitles recorded for cutting; "
                "add them with avs set-subtitles",
            )
        )
    lines = load_text_lines(subtitles)
    if not lines:
        raise ValueError(say(f"{subtitles.name} 里没有台词", f"{subtitles.name} has no lines"))
    offset, agreement = measure_offset(lines, cut)
    if agreement < MIN_AGREEMENT:
        raise ValueError(
            say(
                f"{subtitles.name} 和这一集切片段用的字幕最多只重合 {agreement:.0%}，"
                f"不到 {MIN_AGREEMENT:.0%}，多半不是这一集的字幕",
                f"{subtitles.name} overlaps this episode's subtitles by at most {agreement:.0%}, "
                f"below {MIN_AGREEMENT:.0%}; it is probably for another episode",
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
    }
    write_json(directory / "episode.json", {**episode, **result})
    return {"episode": episode["name"], **result, "matched": round(matched, 4)}


def next_episode_name(workspace: Path) -> str:
    """工作区里下一个没用过的 `epNN`。"""
    folder = workspace / "episodes"
    names = [p.name for p in folder.iterdir()] if folder.is_dir() else []
    numbers = [int(m.group(1)) for n in names if (m := re.fullmatch(r"ep(\d+)", n))]
    return f"ep{max(numbers, default=0) + 1:02d}"


def find_episode_by_video(workspace: Path, video: Path) -> str | None:
    """工作区里已经用这个视频处理过的那一集；没有就是 None。"""
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
    """一条命令加一集：`prepare`、界面要用的几个声纹，有日文字幕就顺手配上。

    中途出错时，做完的步骤留着，再跑同一条命令从断的地方接着做：`prepare` 写出 episode.json
    才算做完，声纹有缓存。`prepare` 自己失败时，删掉它建了一半的目录，免得下次被
    「输出目录已存在」挡住。没给集名时，先找用同一个视频处理过的集，找不到再取下一个 `epNN`。
    """
    from avs.app.workspace import DEFAULT_MODELS, GROUPING_MODEL

    if name is None:
        name = find_episode_by_video(workspace, video) or next_episode_name(workspace)
    validate_name(name)
    out = workspace / "episodes" / name
    device = resolve_device(device)
    say(f"{name}：用 {device} 计算，目录 {out}")

    if (out / "episode.json").exists():
        episode, rows = load_episode(out)
        if episode.get("video") != str(video.resolve()):
            raise ValueError(f"{name} 已经用另一个视频处理过：{episode.get('video')}")
        say(f"已经切好 {len(rows)} 条片段，接着往下做")
    else:
        if out.exists():
            raise ValueError(f"{out} 已存在但不是处理好的一集，确认没用后删掉再试")
        say("抽音轨、抠人声、按字幕切片段（这一步最慢）")
        try:
            result = prepare(video, subtitles, out, name, None, offset, device, audio)
        except BaseException:
            if out.exists():
                shutil.rmtree(out)
            raise
        say(f"切出 {result['segments']} 条片段，字幕偏移 {result['offset']:+.2f} 秒")

    models = list(dict.fromkeys((*DEFAULT_MODELS, GROUPING_MODEL)))
    for model in models:
        say(f"算声纹：{model}")
        embed(out, model, device)

    if text_subtitles is not None:
        say("配台词字幕")
        own = attach_text_subtitles(out, text_subtitles)
        say(f"偏移 {own['text_subtitle_offset']:+.2f} 秒，{own['matched']:.1%} 的片段碰得到台词")

    _, rows = load_episode(out)
    return {"episode": name, "directory": str(out), "segments": len(rows), "models": models}


def extend_segments(directory: Path, subtitle: Path, floor: float = MIN_SECONDS) -> dict[str, Any]:
    """把字幕里没有对应片段的对白行补进这一集的片段表，已有片段一个不动。

    片段 ID 是集名加时间范围的哈希，跟邻居无关，所以只增不改的话既有标签和归档仍然对得上，
    不用重标。代价是声纹缓存会失效，需要重跑 `embed`。

    补进来的行里必然混着解说、群体欢呼这类不属于任何角色的声音；不在这里猜，
    统一收进来交给人耳判断，标注时标「其他」。
    """
    from avs.audio import audio_info
    from avs.evaluation.coverage import align_to_segments, uncovered_lines
    from avs.stages.subtitle import load_dialogue

    episode, rows = load_episode(directory)
    lines = load_dialogue(subtitle)
    if not lines:
        raise ValueError(f"{subtitle} 里没有对白行，检查字幕样式名")
    offset, inside = align_to_segments(lines, rows)
    if inside < len(rows) * 0.9:
        raise ValueError(f"只有 {inside}/{len(rows)} 条片段落在字幕行内，这份字幕多半不是这一集")

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
        raise ValueError("没有可补的对白行，片段表未改动")

    spans = [{"start": r["start"], "end": r["end"]} for r in rows] + added
    combined = segment_rows(episode["name"], spans)
    kept = {r["id"] for r in rows}
    if not kept <= {r["id"] for r in combined}:
        raise ValueError("补片段改动了已有片段，已中止")
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
    """声纹与输入绑定；已有完整缓存直接复用。短片段保留在片段表中。"""
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
        raise ValueError(f"{directory} 声纹缓存已过期，重新运行 embed")
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
        raise ValueError("声纹矩阵与片段信息不一致")
    if len(vectors) and not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError("声纹不是单位长度向量")
    return records, vectors


def relative_threshold(directories: list[Path], model: str = ANIME_VA) -> float:
    """按这些集拼成的池子自己的距离算分界线。见 stages/cluster.py 的 pool_threshold。"""
    import numpy as np

    from avs.stages.cluster import POOL_MULTIPLIERS, pool_threshold

    if model not in POOL_MULTIPLIERS:
        raise ValueError(f"{model} 还没有按池子定分界线用的倍数，先用 avs drift 量一个出来")
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
        raise ValueError(f"连接规则只能是 {', '.join(METHODS)}，收到 {method}")

    if out.exists():
        raise ValueError(f"输出已存在，使用新文件以保留上次分组：{out}")
    if not directories or len({p.resolve() for p in directories}) != len(directories):
        raise ValueError("至少需要一个不重复的集目录")
    if not math.isfinite(threshold) or not 0 < threshold <= 2:
        raise ValueError("距离阈值必须在 0 到 2 之间")
    episodes = {}
    all_rows = []
    records = []
    matrices = []
    for directory in directories:
        episode, rows = load_episode(directory)
        if episode["name"] in episodes:
            raise ValueError("集名重复，请为各集使用不同名字")
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
    # 按首次出现的片段顺序给组编号；小组保留，不合并到杂项桶。
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
        raise ValueError("请提供当前 group 命令生成的分组文件")
    if out.exists():
        raise ValueError(f"导出目录已存在，请用新目录：{out}")
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
