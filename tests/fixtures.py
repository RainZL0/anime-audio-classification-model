"""Small episode folders shared by the tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from avs.project import cache_signature, segment_rows, write_json


def _unit(matrix: np.ndarray) -> np.ndarray:
    return (matrix / np.linalg.norm(matrix, axis=1, keepdims=True)).astype(np.float32)


def episode(root: Path, name: str, vectors: np.ndarray) -> Path:
    """One episode where every clip has a voiceprint; the directions are given by the caller."""
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    sf.write(vocals, np.zeros(16000), 16000)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(name.encode())
    write_json(
        directory / "episode.json",
        {
            "schema": "avs.episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(analysis),
            "source": str(vocals),
            "sample_rate": 16000,
        },
    )
    rows = segment_rows(name, [{"start": i, "end": i + 0.9} for i in range(len(vectors))])
    write_json(directory / "segments.json", rows)
    cache = directory / "embeddings/redimnet2-b6"
    cache.mkdir(parents=True)
    np.save(cache / "vectors.npy", _unit(vectors))
    write_json(cache / "metadata.json", rows)
    write_json(cache / "cache.json", cache_signature(directory, "redimnet2-b6"))
    return directory
