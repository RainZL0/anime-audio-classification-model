"""Current data format: one description file and one clip table per episode. The cache is checked
against the input content."""

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


def resolve_device(device: str) -> str:
    """`auto` uses `cuda` if there is an NVIDIA GPU, otherwise `cpu`. Other values are returned as
    they are."""
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def time_key(row: dict[str, Any]) -> tuple[float, float]:
    return round(float(row["start"]), 3), round(float(row["end"]), 3)


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise ValueError(
            "Episode name may only contain English letters, digits, underscores and hyphens"
        )
    return name


def segment_rows(episode: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clips are not filtered by audio quality. The ID is tied to the episode name and time, so
    reordering or regrouping does not change it."""
    validate_name(episode)
    rows = []
    seen = set()
    for row in sorted(spans, key=lambda r: (float(r["start"]), float(r["end"]))):
        start, end = float(row["start"]), float(row["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError("Clip times must be finite, and 0 <= start < end")
        key = time_key(row)
        if key in seen:
            raise ValueError("Clip has a duplicate time range (in milliseconds)")
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
        raise ValueError(f"Not a current episode directory: {directory}")
    validate_name(episode["name"])
    rows = read_json(directory / "segments.json")
    if segment_rows(episode["name"], rows) != rows:
        raise ValueError(f"{directory}: clip IDs, episode name, or order do not match")
    return episode, rows


def cache_signature(directory: Path, model: str) -> dict[str, str]:
    """Fingerprint of the voiceprint cache. If any of these items changes, the old cache must be
    thrown away and recomputed.

    The minimum duration must also be recorded, because it decides which clips get a voiceprint.
    Without this item, after raising the minimum, the old cache would still pass the check, grouping
    would keep using short clips that should have been dropped, and there would be no error.
    """
    from avs.embeddings.extract import MIN_SECONDS

    episode, _ = load_episode(directory)
    signature = {
        "model": model,
        "segments_sha256": digest(directory / "segments.json"),
        "analysis_sha256": digest(Path(episode["analysis"])),
        "min_seconds": f"{MIN_SECONDS:.3f}",
    }
    return signature


def cache_dir(directory: Path, model: str) -> Path:
    validate_name(model)
    return directory / "embeddings" / model
