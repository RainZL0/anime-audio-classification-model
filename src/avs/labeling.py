"""Arrange identity labeling: random sampling over a whole episode, or label only the clips changed
by a candidate grouping, according to a plan.

Each submission is saved straight to the human archive, atomically. The plan only decides which
clips to label. The archive still stays sorted by time, because the labeler
finds people by going forward along the picture, and jumping back and forth in time is slower than
labeling a few more clips.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import threading
from collections import Counter
from contextlib import suppress
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from avs.project import digest, load_episode, read_json, time_key, write_json

SPECIAL = {
    "__unclear__": "unclear",
    "__multiple__": "more than one person",
    "__not_speech__": "not speech",
}
PLAN_SCHEMA = "avs.label_plan.v1"
VIDEO_PAD = 0.5
"""Seconds to keep before and after each video cut. The dialogue line alone often does not show who
is speaking, so some context is needed."""
VIDEO_HEIGHT = 360
"""Height of the exported picture. Tall enough to see who is speaking. Smaller means faster cutting
and loading."""


def build_plan(
    candidate: Path, baseline: Path, annotations: list[Path], out: Path
) -> dict[str, Any]:
    """List short clips that the candidate grouping attaches to several groups and that the human
    archive does not cover yet, split by episode and sorted by time.

    These clips decide whether the candidate is worth replacing the default grouping. They almost
    never have labels, and the candidate only lowers missed merges by attaching them.
    The plan also records whether each clip is assigned the same way in both groupings. The ones
    marked `moved` are clips where the two rules give different answers.
    """
    from avs.evaluation.identity import annotated_clip_ids
    from avs.stages.cluster import SHORT_SECONDS

    if out.exists():
        raise ValueError(
            f"The plan already exists. Use a new file name to keep the previous plan: {out}"
        )
    candidate_data = read_json(candidate)
    baseline_data = read_json(baseline)
    rows = {r["id"]: r for r in candidate_data["assignments"]}
    baseline_groups = {r["id"]: r["speaker"] for r in baseline_data["assignments"]}
    if rows.keys() != baseline_groups.keys():
        raise ValueError("The clips in the two groupings do not match, so they cannot be compared")
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
        raise ValueError(
            "No clips need new labels. The candidate does not change any unlabeled short clip"
        )

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
        "note": "Only schedules clips that the human archive does not cover yet. "
        "After labeling, accept using only this new archive; do not mix it with the old labels.",
    }
    write_json(out, plan)
    return plan


def build_sample(
    directory: Path,
    archive: Path,
    count: int,
    plan: Path | None = None,
    every: bool = False,
) -> dict[str, Any]:
    episode, rows = load_episode(directory)
    if count < 1:
        raise ValueError("The number of clips to sample must be positive")
    if every and plan is not None:
        raise ValueError("Labeling a whole episode and labeling by plan can only choose one")
    if archive.exists():
        data: dict[str, Any] = read_json(archive)
        source = str(data["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source != Path(episode["vocals"]).name:
            raise ValueError(
                "The existing labels are not for this episode, so they cannot be overwritten"
            )
        times = {time_key(row) for row in rows}
        if any(time_key(c) not in times for c in data["clips"]):
            raise ValueError(
                "The existing labels include old clip cuts. Use a different archive file name to "
                "keep the old labels"
            )
        if every:
            data = _fill_in(data, rows, archive)
        return data
    if every:
        chosen = list(rows)
        method = "Whole episode, all clips in time order, confirm identities against the picture"
        extra: dict[str, Any] = {}
    elif plan is None:
        chosen = random.Random(0).sample(rows, min(count, len(rows)))
        method = "All clips, random sample, confirm identities against the picture"
        extra = {"seed": 0}
    else:
        chosen, extra = _plan_rows(plan, episode, rows)
        method = (
            "Short clips changed by the candidate grouping, "
            "labeled by plan, confirm identities against the picture"
        )
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


def _fill_in(data: dict[str, Any], rows: list[dict[str, Any]], archive: Path) -> dict[str, Any]:
    """When labeling a whole episode, append clips that were added to the clip table later to the
    existing archive as empty labels. Labeled clips are not touched.

    Clip IDs are a hash of the episode name and time range, so adding clips does not change existing
    clips. Old labels therefore stay valid, and only the newly appearing clips need to be added to
    be labeled.
    """
    have = {time_key(clip) for clip in data["clips"]}
    fresh = [row for row in rows if time_key(row) not in have]
    if not fresh:
        return data
    clips = [*data["clips"], *(dict(row, clip_id=row["id"], name=None) for row in fresh)]
    updated = {**data, "clips": sorted(clips, key=lambda c: (c["start"], c["end"]))}
    write_json(archive, updated)
    return updated


def known_names(sources: list[Path]) -> list[str]:
    """Character names for the page's name list, with special labels removed. These are names only;
    they do not take part in any scoring.

    Both sources are read: human archives (taken from the name field of `clips`, sorted from most to
    fewest clips), and name-only list files (the `names` list, in file order).
    Common characters come first, so the number keys land on the names you really use often. The
    name list comes after the archives, and a name found in both keeps the position where it first
    appears.
    """
    found: Counter[str] = Counter()
    listed: list[str] = []
    for path in sources:
        data = read_json(path)
        if "names" in data:
            listed.extend(n for n in data["names"] if n and not n.startswith("__"))
            continue
        for clip in data["clips"]:
            name = clip.get("name")
            if name and not name.startswith("__"):
                found[name] += 1
    ordered = [name for name, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ordered + [n for n in dict.fromkeys(listed) if n not in found]


def stamp(start: float) -> str:
    """Minutes:seconds, matching the video progress bar."""
    return f"{int(start // 60):02d}:{start % 60:05.2f}"


def reference_clips(archives: list[Path], directory: Path) -> dict[str, list[dict[str, Any]]]:
    """The old-label clips under each existing character name, for playing back during labeling to
    compare.

    Old archives may record audio track paths that have since moved, so the matching vocal track is
    found by file name in each episode under `runs/episodes`.
    An archive with no match is skipped entirely: it is better to have no reference audio than to
    fill the gap with a different track.
    """
    root = directory.resolve().parent
    sources: dict[str, tuple[str, str]] = {}
    for candidate in sorted(root.iterdir()) if root.is_dir() else []:
        if not (candidate / "episode.json").exists():
            continue
        own, _ = load_episode(candidate)
        sources[Path(own["vocals"]).name] = (own["name"], own["vocals"])

    history: dict[str, list[dict[str, Any]]] = {}
    seen = 0
    for path in archives:
        data = read_json(path)
        if "clips" not in data:
            continue
        found = sources.get(str(data["source"]).replace("\\", "/").rsplit("/", 1)[-1])
        if found is None:
            continue
        name_of_episode, vocals = found
        for clip in data["clips"]:
            name = clip.get("name")
            if not name or name.startswith("__"):
                continue
            seen += 1
            history.setdefault(name, []).append(
                {
                    "file": f"ref_{seen:04d}.wav",
                    "episode": name_of_episode,
                    "stamp": stamp(float(clip["start"])),
                    "seconds": round(float(clip["end"]) - float(clip["start"]), 2),
                    "vocals": vocals,
                    "start": float(clip["start"]),
                    "end": float(clip["end"]),
                }
            )
    return history


def cut_video(video: Path, start: float, end: float, out: Path) -> None:
    """Cut a short piece of video with ffmpeg and convert it to H.264 mp4, which browsers can always
    play.

    The source is HEVC, and browser support for it depends on the browser version, so it cannot be
    relied on. So this always transcodes, and also scales the picture down to `VIDEO_HEIGHT`.
    In measurements, a 2-3 second clip is cut in under half a second, so clips are cut on demand
    rather than all in advance.
    `-ss` goes before `-i` for fast seeking. Without this, every cut would decode from the start.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(".part.mp4")
    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.05, end - start):.3f}",
        "-i", str(video),
        "-vf", f"scale=-2:{VIDEO_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", "-y", str(temporary),
    ]  # fmt: skip
    try:
        subprocess.run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            f"Video cut failed. Check that ffmpeg is available and the video can be read: {exc}"
        ) from exc
    temporary.replace(out)


def _cut(sf: Any, vocals: str, start: float, end: float, out: Path) -> None:
    rate = sf.info(vocals).samplerate
    wave, wrote = sf.read(vocals, start=int(start * rate), stop=int(end * rate), always_2d=True)
    sf.write(out, wave, wrote, subtype="PCM_24")


def _plan_rows(
    plan: Path, episode: dict[str, Any], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = read_json(plan)
    if data.get("schema") != PLAN_SCHEMA:
        raise ValueError("Not a labeling plan file")
    entries = data["episodes"].get(episode["name"])
    if not entries:
        raise ValueError(f"The plan has no clips for {episode['name']} to label")
    by_id = {row["id"]: row for row in rows}
    missing = [e["clip_id"] for e in entries if e["clip_id"] not in by_id]
    if missing:
        raise ValueError(
            "The plan's clips are not in the current cuts. If the cuts change, the plan must be "
            "made again"
        )
    return [by_id[e["clip_id"]] for e in entries], {"plan": str(plan.resolve())}


def apply_names(data: dict[str, Any], names: Any) -> dict[str, Any]:
    valid = {c["clip_id"] for c in data["clips"]}
    if (
        not isinstance(names, dict)
        or any(k not in valid for k in names)
        or any(not isinstance(v, str) or not v.strip() for v in names.values())
    ):
        raise ValueError("The submission must be non-empty names keyed by this archive's clip IDs")
    return {**data, "clips": [dict(c, name=names.get(c["clip_id"])) for c in data["clips"]]}


def run(
    directory: Path,
    archive: Path,
    count: int,
    port: int,
    plan: Path | None = None,
    known: list[Path] | None = None,
    every: bool = False,
    video: Path | None = None,
) -> None:
    import soundfile as sf

    from avs.label_page import PAGE_NAMES

    archives = _roster_archives(known, plan)
    data = build_sample(directory, archive, count, plan, every)
    roster = known_names(archives)
    history = reference_clips(archives, directory)
    episode, _ = load_episode(directory)
    vocals = episode["vocals"]
    clip_dir = directory / "label_audio" / archive.stem
    clip_dir.mkdir(parents=True, exist_ok=True)
    names = {c["clip_id"]: c["name"] for c in data["clips"] if c.get("name")}
    clips = []
    for c in data["clips"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", c["clip_id"]):
            raise ValueError("A clip ID cannot be used as a file name")
        _cut(sf, vocals, c["start"], c["end"], clip_dir / f"{c['clip_id']}.wav")
        clips.append(
            {
                "id": c["clip_id"],
                "stamp": stamp(c["start"]),
                "seconds": round(c["end"] - c["start"], 2),
            }
        )
    # Also cut the reference audio for the old labels. vocals/start/end are only used for cutting,
    # so they do not need to be sent to the page.
    for entries in history.values():
        for entry in entries:
            source, start, end = entry.pop("vocals"), entry.pop("start"), entry.pop("end")
            _cut(sf, source, start, end, clip_dir / entry["file"])
    page = PAGE_NAMES
    for key, value in (
        ("__CLIPS__", clips),
        ("__NAMES__", names),
        ("__SPECIAL__", SPECIAL),
        ("__KNOWN__", roster),
        ("__HISTORY__", history),
        ("__VIDEO__", video is not None),
    ):
        page = page.replace(key, json.dumps(value, ensure_ascii=False).replace("<", "\\u003c"))
    (clip_dir / "index.html").write_text(page, encoding="utf-8")

    spans = {c["clip_id"]: (float(c["start"]), float(c["end"])) for c in data["clips"]}
    saving = threading.Lock()
    cutting = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(clip_dir), **kwargs)

        def send_head(self) -> Any:
            # The video is cut on demand: a clip is only cut once the user actually reaches it.
            # Clips never reached are never cut.
            wanted = re.fullmatch(r"/video/([A-Za-z0-9_-]+)\.mp4", self.path)
            if wanted and video is not None:
                target = clip_dir / "video" / f"{wanted[1]}.mp4"
                span = spans.get(wanted[1])
                if span is None:
                    self.send_error(404)
                    return None
                with cutting:
                    if not target.exists():
                        try:
                            cut_video(video, span[0] - VIDEO_PAD, span[1] + VIDEO_PAD, target)
                        except ValueError as exc:
                            self.send_error(500, str(exc).encode("ascii", "replace").decode())
                            return None
            return super().send_head()

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/save":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError("The submission is too large or empty")
                names = json.loads(self.rfile.read(length))
                with saving:
                    write_json(archive, apply_names(data, names))
            except (ValueError, OSError) as exc:
                self.send_error(400, str(exc).encode("ascii", "replace").decode())
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    print(
        f"Open http://127.0.0.1:{port}/ . Each label is saved straight to {archive}. "
        f"The page's name list has {len(roster)} existing character names, "
        f"{sum(len(v) for v in history.values())} old labels can be played back for comparison"
        + (
            "; pictures are cut from the video on demand"
            if video
            else "; no --video given, so only the separated vocals are available"
        ),
        flush=True,
    )
    # Multi-threaded: cutting video on demand takes a few hundred milliseconds. A single thread
    # would block the save requests that arrive during that time.
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server, suppress(KeyboardInterrupt):
        server.serve_forever()


def _roster_archives(known: list[Path] | None, plan: Path | None) -> list[Path]:
    """If no name list source is given, use the human archives recorded in the plan, so the names
    match the old labels."""
    if known:
        return known
    if plan is None:
        return []
    paths = [Path(item["path"]) for item in read_json(plan).get("annotations", [])]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise ValueError(
            f"An archive recorded in the plan is no longer where it was. "
            f"Use --known to specify it: {missing[0]}"
        )
    return paths
