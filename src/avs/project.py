"""当前数据格式：一集一份说明和片段表，缓存由输入内容校验。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def time_key(row: dict[str, Any]) -> tuple[float, float]:
    return round(float(row["start"]), 3), round(float(row["end"]), 3)


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise ValueError("集名只能含英文字母、数字、下划线和连字符")
    return name


def segment_rows(episode: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """片段不按音质筛；ID 绑定集名和时间，重排或重新分组不变。"""
    validate_name(episode)
    rows = []
    seen = set()
    for row in sorted(spans, key=lambda r: (float(r["start"]), float(r["end"]))):
        start, end = float(row["start"]), float(row["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError("片段时间必须有限，且 0 <= start < end")
        key = time_key(row)
        if key in seen:
            raise ValueError("片段有重复的毫秒时间范围")
        seen.add(key)
        identity = f"{episode}:{key[0]:.3f}:{key[1]:.3f}"
        rows.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                "episode": episode,
                "start": start,
                "end": end,
            }
        )
    return rows


def load_episode(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    episode = read_json(directory / "episode.json")
    if episode.get("schema") != "avs.episode.v1":
        raise ValueError(f"不是当前的一集目录：{directory}")
    validate_name(episode["name"])
    rows = read_json(directory / "segments.json")
    if segment_rows(episode["name"], rows) != rows:
        raise ValueError(f"{directory} 的片段 ID、集名或顺序不一致")
    return episode, rows


def cache_signature(directory: Path, model: str, window: float = 0.0) -> dict[str, str]:
    """声纹缓存的指纹。窗口为 0 时不写这一项，好让改动之前算好的缓存继续有效。"""
    episode, _ = load_episode(directory)
    signature = {
        "model": model,
        "segments_sha256": digest(directory / "segments.json"),
        "analysis_sha256": digest(Path(episode["analysis"])),
    }
    if window:
        signature["window_seconds"] = f"{window:.3f}"
    return signature


def cache_dir(directory: Path, model: str, window: float = 0.0) -> Path:
    """不同听音窗口算出来的是不同的声纹，分开放，免得互相顶掉。"""
    validate_name(model)
    name = model if not window else f"{model}@w{window:g}"
    return directory / "embeddings" / name
