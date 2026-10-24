"""A small workspace in a temporary folder, served by avoc, for the browser tests (Playwright).

Two episodes of 24 lines each, spoken by three voices, with subtitles but no video. Nothing is
labeled, so every run starts from the same place. The folder is deleted when the server stops.

Run from the repository root: uv run python web/e2e/server.py PORT
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import uvicorn

from avoc.app.server import AppState, create_app
from avoc.project import cache_signature, segment_rows, write_json

MODEL = "redimnet2-b6"
LINE_SECONDS, GAP_SECONDS, RATE = 1.5, 0.3, 16000
LINES = [
    "おはようございます",
    "今日はいい天気ですね",
    "トレーナーさん、こっちです",
    "走るのが大好きなんです",
    "次のレースも頑張ります",
    "負けませんよ",
    "えっ、本当ですか",
    "ちょっと待ってください",
]


def srt_time(seconds: float) -> str:
    whole, milliseconds = int(seconds), round(seconds % 1 * 1000)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d},{milliseconds:03d}"


def episode(episodes: Path, name: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    folder = episodes / name
    folder.mkdir(parents=True)
    spans = [
        {
            "start": i * (LINE_SECONDS + GAP_SECONDS),
            "end": i * (LINE_SECONDS + GAP_SECONDS) + LINE_SECONDS,
        }
        for i in range(24)
    ]
    vocals = folder / "vocals.wav"
    sf.write(vocals, np.zeros(int((spans[-1]["end"] + 1) * RATE), dtype=np.float32), RATE)
    subtitles = folder / "subtitles.srt"
    subtitles.write_text(
        "\n".join(
            f"{i + 1}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{LINES[i % len(LINES)]}\n"
            for i, s in enumerate(spans)
        ),
        encoding="utf-8",
    )
    write_json(
        folder / "episode.json",
        {
            "schema": "episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(vocals),
            "source": str(vocals),
            "sample_rate": RATE,
            "subtitles": str(subtitles),
            "subtitle_offset": 0.0,
            "spoken_language": "ja",
        },
    )
    rows = segment_rows(name, spans)
    write_json(folder / "segments.json", rows)
    # Three voices, each a direction in the voiceprint space with a little noise.
    voices = np.eye(8)[[i % 3 for i in range(len(rows))]] + rng.normal(0, 0.05, (len(rows), 8))
    voices /= np.linalg.norm(voices, axis=1, keepdims=True)
    cache = folder / "embeddings" / MODEL
    cache.mkdir(parents=True)
    np.save(cache / "vectors.npy", voices.astype(np.float32))
    write_json(cache / "metadata.json", rows)
    write_json(cache / "cache.json", cache_signature(folder, MODEL))


def main() -> None:
    port = int(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix="avoc-e2e-") as temporary:
        root = Path(temporary)
        for number in (1, 2):
            episode(root / "episodes", f"ep{number:02d}", number)
        state = AppState(root, (MODEL,), grouping=MODEL)
        uvicorn.run(create_app(state), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
