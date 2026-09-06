"""字幕片段、声纹缓存、身份分组和导出各自独立，调分组不跑音频模型。"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from avs.embeddings.extract import FRONTIER, MIN_SECONDS, embed_segments
from avs.project import (
    cache_dir,
    cache_signature,
    digest,
    load_episode,
    read_json,
    segment_rows,
    time_key,
    validate_name,
    write_json,
)


def prepare(
    audio: Path,
    subtitles: Path,
    out: Path,
    name: str,
    vocals: Path | None = None,
    offset: float | None = None,
    device: str = "cuda",
) -> dict[str, Any]:
    """以每行字幕为候选。偏移可显式提供，否则用说话时间线自动量。"""
    from avs.audio import audio_info, diarize, make_analysis_copy, separate_vocals
    from avs.stages.subtitle import MIN_OVERLAP_RATIO, find_offset, load_lines

    validate_name(name)
    if out.exists():
        raise ValueError(f"输出目录已存在：{out}")
    if offset is not None and not math.isfinite(offset):
        raise ValueError("字幕偏移必须是有限数值")
    lines = load_lines(subtitles)
    if not lines:
        raise ValueError("字幕中没有对白行")
    source = audio_info(audio)
    if source.sample_rate < 32000:
        raise ValueError("原始音轨采样率低于 32000 Hz")
    if vocals:
        info = audio_info(vocals)
        if info.sample_rate != source.sample_rate or abs(info.duration - source.duration) > 0.1:
            raise ValueError("复用人声轨的采样率或时长与原始音轨不一致")
    out.mkdir(parents=True)
    if vocals is None:
        vocals = separate_vocals(audio, out / "separated", Path("models"), source.sample_rate)
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


def extend_segments(directory: Path, subtitle: Path, floor: float = MIN_SECONDS) -> dict[str, Any]:
    """把字幕里没有对应片段的对白行补进这一集的片段表，已有片段一个不动。

    片段 ID 是集名加时间范围的哈希，跟邻居无关，所以只增不改的话既有标签和归档仍然对得上，
    不用重标。代价是声纹缓存会失效，需要重跑 `embed`。

    补进来的行里必然混着解说、群体欢呼这类不属于任何角色的声音；不在这里猜，
    统一收进来交给人耳判断，标注页有 `__not_speech__` 之类的标签可用。
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
    directory: Path, model: str = FRONTIER, device: str = "cuda", window: float = 0.0
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
            Path(episode["analysis"]), eligible, model, device, window
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


def group(
    directories: list[Path],
    out: Path,
    threshold: float = 0.5,
    model: str = FRONTIER,
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
