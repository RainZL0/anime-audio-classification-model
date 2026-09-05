"""从全量片段随机抽身份标注；每次提交直接原子保存到人工归档。"""

from __future__ import annotations

import json
import random
import re
from contextlib import suppress
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from avs.project import load_episode, read_json, time_key, write_json

SPECIAL = {"__unclear__": "无法确认", "__multiple__": "不止一个人", "__not_speech__": "不是说话"}


def build_sample(directory: Path, archive: Path, count: int) -> dict[str, Any]:
    episode, rows = load_episode(directory)
    if count < 1:
        raise ValueError("抽样条数必须为正数")
    if archive.exists():
        data: dict[str, Any] = read_json(archive)
        source = str(data["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source != Path(episode["vocals"]).name:
            raise ValueError("已有标注不是这一集，不能覆盖")
        times = {time_key(row) for row in rows}
        if any(time_key(c) not in times for c in data["clips"]):
            raise ValueError("已有标注包含旧切段，换一个归档文件名以保留旧标签")
        return data
    chosen = random.Random(0).sample(rows, min(count, len(rows)))
    data = {
        "source": episode["vocals"],
        "episode": episode["name"],
        "method": "全量片段随机抽样，对照画面确认身份",
        "seed": 0,
        "clips": [
            dict(row, clip_id=row["id"], name=None)
            for row in sorted(chosen, key=lambda r: r["start"])
        ],
    }
    write_json(archive, data)
    return data


def apply_names(data: dict[str, Any], names: Any) -> dict[str, Any]:
    valid = {c["clip_id"] for c in data["clips"]}
    if (
        not isinstance(names, dict)
        or any(k not in valid for k in names)
        or any(not isinstance(v, str) or not v.strip() for v in names.values())
    ):
        raise ValueError("提交必须是本次片段 ID 对应的非空人名")
    return {**data, "clips": [dict(c, name=names.get(c["clip_id"])) for c in data["clips"]]}


def run(directory: Path, archive: Path, count: int, port: int) -> None:
    import soundfile as sf

    from avs.label_page import PAGE_NAMES

    data = build_sample(directory, archive, count)
    episode, _ = load_episode(directory)
    vocals = episode["vocals"]
    clip_dir = directory / "label_audio" / archive.stem
    clip_dir.mkdir(parents=True, exist_ok=True)
    names = {c["clip_id"]: c["name"] for c in data["clips"] if c.get("name")}
    clips = []
    for c in data["clips"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", c["clip_id"]):
            raise ValueError("片段 ID 不能用作文件名")
        info = sf.info(vocals)
        wave, rate = sf.read(
            vocals,
            start=int(c["start"] * info.samplerate),
            stop=int(c["end"] * info.samplerate),
            always_2d=True,
        )
        sf.write(clip_dir / f"{c['clip_id']}.wav", wave, rate, subtype="PCM_24")
        clips.append(
            {
                "id": c["clip_id"],
                "stamp": f"{int(c['start'] // 60):02d}:{c['start'] % 60:05.2f}",
                "seconds": round(c["end"] - c["start"], 2),
            }
        )
    page = PAGE_NAMES
    for key, value in (("__CLIPS__", clips), ("__NAMES__", names), ("__SPECIAL__", SPECIAL)):
        page = page.replace(key, json.dumps(value, ensure_ascii=False).replace("<", "\\u003c"))
    (clip_dir / "index.html").write_text(page, encoding="utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(clip_dir), **kwargs)

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/save":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError("提交过大或为空")
                names = json.loads(self.rfile.read(length))
                updated = apply_names(data, names)
                write_json(archive, updated)
            except (ValueError, OSError) as exc:
                self.send_error(400, str(exc).encode("ascii", "replace").decode())
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    print(f"打开 http://127.0.0.1:{port}/ ，每条直接保存到 {archive}", flush=True)
    with HTTPServer(("127.0.0.1", port), Handler) as server, suppress(KeyboardInterrupt):
        server.serve_forever()
