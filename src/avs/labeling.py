"""安排身份标注：整集随机抽样，或按计划只标某个候选分组改动过的片段。

每次提交直接原子保存到人工归档。计划只决定标哪些片段，归档里仍按时间排序，
因为标注者是顺着画面往下找人，来回跳时间点比多标几条还慢。
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from contextlib import suppress
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from avs.project import digest, load_episode, read_json, time_key, write_json

SPECIAL = {"__unclear__": "无法确认", "__multiple__": "不止一个人", "__not_speech__": "不是说话"}
PLAN_SCHEMA = "avs.label_plan.v1"


def build_plan(
    candidate: Path, baseline: Path, annotations: list[Path], out: Path
) -> dict[str, Any]:
    """列出候选分组挂进多条组、而人工归档还没覆盖的短片段，按集分开、按时间排序。

    这些片段决定候选值不值得替换默认分组：它们几乎都没有标签，而候选正是靠挂上
    它们才把漏合降下来。同时记下每条在两套分组里的归属是否一致，`moved` 的那些
    是两条规则给出不同答案的片段。
    """
    from avs.evaluation.identity import annotated_clip_ids
    from avs.stages.cluster import SHORT_SECONDS

    if out.exists():
        raise ValueError(f"计划已存在，使用新文件名以保留上次计划：{out}")
    candidate_data = read_json(candidate)
    baseline_data = read_json(baseline)
    rows = {r["id"]: r for r in candidate_data["assignments"]}
    baseline_groups = {r["id"]: r["speaker"] for r in baseline_data["assignments"]}
    if rows.keys() != baseline_groups.keys():
        raise ValueError("两份分组的片段不一致，不能对照")
    covered = annotated_clip_ids(candidate_data, annotations)
    sizes = Counter(r["speaker"] for r in rows.values() if r["speaker"] is not None)

    episodes: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows.values(), key=lambda r: (r["episode"], r["start"])):
        group = row["speaker"]
        if group is None or sizes[group] < 2 or row["end"] - row["start"] >= SHORT_SECONDS:
            continue
        if row["id"] in covered:
            continue
        episodes.setdefault(row["episode"], []).append(
            {
                "clip_id": row["id"],
                "start": row["start"],
                "end": row["end"],
                "candidate_group": group,
                "baseline_group": baseline_groups[row["id"]],
                "reason": "moved" if baseline_groups[row["id"]] != group else "kept",
            }
        )
    if not episodes:
        raise ValueError("没有需要新标注的片段，候选没有改动未标注的短片段")

    plan = {
        "schema": PLAN_SCHEMA,
        "candidate": {"path": str(candidate.resolve()), "sha256": digest(candidate)},
        "baseline": {"path": str(baseline.resolve()), "sha256": digest(baseline)},
        "annotations": [{"path": str(p.resolve()), "sha256": digest(p)} for p in annotations],
        "short_seconds": SHORT_SECONDS,
        "episodes": episodes,
        "summary": {
            episode: {
                "clips": len(entries),
                "moved": sum(e["reason"] == "moved" for e in entries),
                "seconds": round(sum(e["end"] - e["start"] for e in entries), 3),
            }
            for episode, entries in episodes.items()
        },
        "note": "只安排人工归档尚未覆盖的片段；标完只用这份新归档验收，不与旧标签混算。",
    }
    write_json(out, plan)
    return plan


def build_sample(
    directory: Path, archive: Path, count: int, plan: Path | None = None
) -> dict[str, Any]:
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
    if plan is None:
        chosen = random.Random(0).sample(rows, min(count, len(rows)))
        method = "全量片段随机抽样，对照画面确认身份"
        extra: dict[str, Any] = {"seed": 0}
    else:
        chosen, extra = _plan_rows(plan, episode, rows)
        method = "按计划标候选分组改动的短片段，对照画面确认身份"
    data = {
        "source": episode["vocals"],
        "episode": episode["name"],
        "method": method,
        **extra,
        "clips": [
            dict(row, clip_id=row["id"], name=None)
            for row in sorted(chosen, key=lambda r: r["start"])
        ],
    }
    write_json(archive, data)
    return data


def _plan_rows(
    plan: Path, episode: dict[str, Any], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = read_json(plan)
    if data.get("schema") != PLAN_SCHEMA:
        raise ValueError("不是标注计划文件")
    entries = data["episodes"].get(episode["name"])
    if not entries:
        raise ValueError(f"计划里没有 {episode['name']} 需要标注的片段")
    by_id = {row["id"]: row for row in rows}
    missing = [e["clip_id"] for e in entries if e["clip_id"] not in by_id]
    if missing:
        raise ValueError("计划里的片段不在当前切段中，切段变了就要重新做计划")
    return [by_id[e["clip_id"]] for e in entries], {"plan": str(plan.resolve())}


def apply_names(data: dict[str, Any], names: Any) -> dict[str, Any]:
    valid = {c["clip_id"] for c in data["clips"]}
    if (
        not isinstance(names, dict)
        or any(k not in valid for k in names)
        or any(not isinstance(v, str) or not v.strip() for v in names.values())
    ):
        raise ValueError("提交必须是本次片段 ID 对应的非空人名")
    return {**data, "clips": [dict(c, name=names.get(c["clip_id"])) for c in data["clips"]]}


def run(directory: Path, archive: Path, count: int, port: int, plan: Path | None = None) -> None:
    import soundfile as sf

    from avs.label_page import PAGE_NAMES

    data = build_sample(directory, archive, count, plan)
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
