"""一个工作区：`episodes/` 下每集一个目录，`labels/` 下放标签记录和角色表。

载入时把每条片段的台词文字从字幕里找回来，按停顿切成场景，再把几个声纹模型的缓存
拼成一张表。片段短于 0.5 秒没有声纹（见 embeddings/extract.py 的 MIN_SECONDS），
这些片段照样出现在界面上，只是机器给不出预测，要人来认。
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

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Workspace:
    root: Path
    episodes: dict[str, dict[str, Any]]
    """集名到 episode.json 的内容，另加一个 `directory`。"""
    clips: list[Clip]
    features: Any
    grouping: Any
    models: tuple[str, ...]
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


def load_workspace(
    root: Path, models: tuple[str, ...] = DEFAULT_MODELS, grouping: str = GROUPING_MODEL
) -> Workspace:
    import numpy as np

    episodes: dict[str, dict[str, Any]] = {}
    clips: list[Clip] = []
    feature_rows: list[Any] = []
    grouping_rows: list[Any] = []
    for directory in episode_dirs(root):
        episode, rows = load_episode(directory)
        episodes[episode["name"]] = {**episode, "directory": str(directory)}
        parts = []
        ids: list[str] | None = None
        for model in (*models, grouping):
            records, vectors = load_embeddings(directory, model)
            order = {r["id"]: i for i, r in enumerate(records)}
            if ids is None:
                ids = [r["id"] for r in records]
            elif set(order) != set(ids):
                raise ValueError(f"{directory} 各声纹模型覆盖的片段不同，重跑 avs embed")
            parts.append(vectors[[order[i] for i in ids]])
        assert ids is not None
        joined = np.concatenate(parts[: len(models)], axis=1)
        joined /= np.linalg.norm(joined, axis=1, keepdims=True)
        position = {clip_id: len(feature_rows) + k for k, clip_id in enumerate(ids)}
        feature_rows.extend(joined)
        grouping_rows.extend(parts[-1])

        lines = subtitle_lines(episode)
        starts = [line[0] for line in lines]
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
    )
