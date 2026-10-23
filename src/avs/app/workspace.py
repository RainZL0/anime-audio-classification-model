"""一个工作区：`episodes/` 下每集一个目录，`labels/` 下放标签记录和角色表。

载入时把每条片段的台词文字从字幕里找回来，按停顿切成场景，再把几个声纹模型的缓存
拼成一张表。片段短于 0.5 秒没有声纹（见 embeddings/extract.py 的 MIN_SECONDS），
这些片段照样出现在界面上，只是机器给不出预测，要人来认。

短于 `SKIP_SECONDS` 又和前后台词都隔得远的片段默认跳过，不要人标，见 `Clip.skipped`。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avs.pipeline import load_embeddings
from avs.project import load_episode

SCENE_GAP = 3.0
"""两句台词之间停顿超过这么多秒，就算换了一场。只用来给对话分段显示，不参与判断身份。"""

DEFAULT_MODELS = ("anime-va", "anime-char", "redimnet2-b6")
"""三个声纹拼在一起最好，见 docs/EXPERIMENTS.md 的「按名字分类」。"""

GROUPING_MODEL = "anime-va"
"""起步分组只用这一个模型，它的分界线 0.70 是量过的，拼起来的声纹没有量过。"""

SKIP_SECONDS = 1.0
"""短于这么多秒的片段拿去训练语音合成基本用不上，默认不要人标。"""

NEIGHBOR_GAP = 0.5
"""短片段和前后台词的间隔不超过这么多秒，就可能是一句长话被字幕切碎了，仍然留给人标。

第 3 集 36 条有名字的 1 秒以下片段里，只有 4 条在 0.5 秒内紧挨同一角色的台词。"""


@dataclass(frozen=True)
class Clip:
    id: str
    episode: str
    start: float
    end: float
    text: str
    scene: int
    row: int | None
    """在声纹表里的行号；没有声纹时是 None。"""
    gap: float | None = None
    """和最近的另一句台词（别的字幕行或别的片段）隔几秒，挨着或重叠是 0；这一集只有它时是 None。"""

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def skipped(self) -> bool:
        """太短又前后没有紧挨的台词，默认不要人标。"""
        return self.duration < SKIP_SECONDS and (self.gap is None or self.gap > NEIGHBOR_GAP)


@dataclass
class Workspace:
    root: Path
    episodes: dict[str, dict[str, Any]]
    """集名到 episode.json 的内容，另加一个 `directory`。"""
    clips: list[Clip]
    features: Any
    grouping: Any
    models: tuple[str, ...]
    skipped: dict[str, str] = field(default_factory=dict)
    """没载入的集名到原因，多半是声纹没算全。"""
    by_id: dict[str, Clip] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_id = {c.id: c for c in self.clips}

    @property
    def labels_dir(self) -> Path:
        return self.root / "labels"


def episode_dirs(root: Path) -> list[Path]:
    folder = root / "episodes"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if (p / "episode.json").exists())


MIN_TEXT_OVERLAP = 0.5
"""片段和一行字幕重叠的部分，至少占两者中较短那段的这么多，才把这行字算成片段的台词。

不按精确时间对，是因为第 1、2 集有一部分片段是早期按语音检测切的，边界不是字幕行。"""


def subtitle_lines(episode: dict[str, Any]) -> list[tuple[float, float, str]]:
    """这一集的字幕行，已经加上偏移，换算到音轨的时间。"""
    from avs.stages.subtitle import load_dialogue

    path = Path(episode.get("subtitles") or "")
    if not path.is_file():
        return []
    offset = float(episode.get("subtitle_offset") or 0.0)
    return [
        (line["start"] + offset, line["end"] + offset, line["text"]) for line in load_dialogue(path)
    ]


def text_for(
    lines: list[tuple[float, float, str]], starts: list[float], start: float, end: float
) -> str:
    """和这段时间重叠够多的字幕行，双语字幕同一时间的几行用斜杠连起来。"""
    found: list[str] = []
    at = bisect.bisect_left(starts, start - 20.0)
    for low, high, text in lines[at:]:
        if low >= end:
            break
        shared = min(high, end) - max(low, start)
        shorter = min(high - low, end - start)
        if shorter > 0 and shared >= MIN_TEXT_OVERLAP * shorter and text not in found:
            found.append(text)
    return " / ".join(found)


def neighbor_gap(
    spans: list[tuple[float, float]],
    at: int,
    lines: list[tuple[float, float, str]],
    line_starts: list[float],
) -> float | None:
    """`spans[at]` 和最近的另一句台词隔几秒。`spans` 是这一集全部片段，按开始时间排好。

    另一句台词可以是别的片段，也可以是没切出片段的字幕行；这条片段自己的台词那几行
    （按 `text_for` 的规则算进它的字幕行）不算。前后 20 秒内都没有就是 None。
    """
    start, end = spans[at]
    span_starts = [s[0] for s in spans]
    low_at = bisect.bisect_left(span_starts, start - 20.0)
    high_at = bisect.bisect_left(span_starts, end + 20.0)
    others = [spans[k] for k in range(low_at, high_at) if k != at]
    for low, high, _ in lines[bisect.bisect_left(line_starts, start - 20.0) :]:
        if low >= end + 20.0:
            break
        shared = min(high, end) - max(low, start)
        shorter = min(high - low, end - start)
        if not (shorter > 0 and shared >= MIN_TEXT_OVERLAP * shorter):
            others.append((low, high))
    if not others:
        return None
    return max(min(max(low - end, start - high) for low, high in others), 0.0)


def load_workspace(
    root: Path, models: tuple[str, ...] = DEFAULT_MODELS, grouping: str = GROUPING_MODEL
) -> Workspace:
    import numpy as np

    episodes: dict[str, dict[str, Any]] = {}
    clips: list[Clip] = []
    feature_rows: list[Any] = []
    grouping_rows: list[Any] = []
    skipped: dict[str, str] = {}
    for directory in episode_dirs(root):
        episode, rows = load_episode(directory)
        try:
            ids, parts = _aligned_vectors(directory, (*models, grouping))
        except (FileNotFoundError, ValueError) as exc:
            # 多半是 avs add 中途断了。跳过这一集，别让整个界面打不开。
            skipped[episode["name"]] = (
                "声纹没算全，再运行一遍加这一集的 avs add 命令会接着算"
                if isinstance(exc, FileNotFoundError)
                else str(exc)
            )
            continue
        episodes[episode["name"]] = {**episode, "directory": str(directory)}
        joined = np.concatenate(parts[: len(models)], axis=1)
        joined /= np.linalg.norm(joined, axis=1, keepdims=True)
        position = {clip_id: len(feature_rows) + k for k, clip_id in enumerate(ids)}
        feature_rows.extend(joined)
        grouping_rows.extend(parts[-1])

        lines = subtitle_lines(episode)
        starts = [line[0] for line in lines]
        spans = sorted((float(row["start"]), float(row["end"])) for row in rows)
        gaps = {spans[k]: neighbor_gap(spans, k, lines, starts) for k in range(len(spans))}
        scene, previous_end = 0, None
        for row in rows:
            if previous_end is not None and row["start"] - previous_end > SCENE_GAP:
                scene += 1
            previous_end = row["end"] if previous_end is None else max(previous_end, row["end"])
            clips.append(
                Clip(
                    id=row["id"],
                    episode=episode["name"],
                    start=float(row["start"]),
                    end=float(row["end"]),
                    text=text_for(lines, starts, float(row["start"]), float(row["end"])),
                    scene=scene,
                    row=position.get(row["id"]),
                    gap=gaps[(float(row["start"]), float(row["end"]))],
                )
            )
    width = feature_rows[0].shape[0] if feature_rows else 0
    return Workspace(
        root=root,
        episodes=episodes,
        clips=clips,
        features=np.stack(feature_rows) if feature_rows else np.empty((0, width)),
        grouping=np.stack(grouping_rows) if grouping_rows else np.empty((0, 0)),
        models=models,
        skipped=skipped,
    )


def _aligned_vectors(directory: Path, models: tuple[str, ...]) -> tuple[list[str], list[Any]]:
    """各模型的声纹按同一个片段顺序排好。缓存缺了或过期时抛错。"""
    parts = []
    ids: list[str] | None = None
    for model in models:
        records, vectors = load_embeddings(directory, model)
        order = {r["id"]: i for i, r in enumerate(records)}
        if ids is None:
            ids = [r["id"] for r in records]
        elif set(order) != set(ids):
            raise ValueError(f"{directory} 各声纹模型覆盖的片段不同，重跑 avs embed")
        parts.append(vectors[[order[i] for i in ids]])
    assert ids is not None
    return ids, parts
