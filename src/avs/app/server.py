"""本地服务：给网页提供片段、预测和媒体，接收标注，每次标注后重训。

只监听 127.0.0.1。状态都在内存里，改动先写进标签记录再更新内存，进程崩了重开就能接着用。
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from avs.app.labels import OLD_FLAGS, OTHER, LabelStore, flag_of
from avs.app.model import AUTO_CONFIDENCE, Guess, train_and_predict
from avs.app.workspace import DEFAULT_MODELS, GROUPING_MODEL, Clip, load_workspace
from avs.labeling import VIDEO_PAD, cut_video

STATIC = Path(__file__).parent / "static"
GROUP_THRESHOLD = 0.70
"""起步分组用 anime-va 的分界线，见 docs/DECISIONS.md。"""
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
MAYBE_FLOOR = 0.05
"""角色视图「可能漏掉的」只列「是 TA」的概率不低于这个数的片段。"""
UNUSABLE = "人标了质量低"
"""导出时跳过人标了「质量低」的片段，在 rejected.tsv 里写的原因。"""
MAYBE_LIMIT = 100
"""「可能漏掉的」最多列这么多条，从最像的往下排。"""
CONTEXT_SECONDS = (5, 15)
"""看不出是谁时，可以临时前后各多放这么多秒（按 L 依次切换），只在人要的时候切。"""
PREFETCH_SECONDS = 60.0
"""看到一句时，在后台先把前后这么多秒内的台词片段切好，往附近跳就不用等，再接着切后面的。"""
PREFETCH_WORKERS = 2
"""后台同时切几段。一段画面要切半秒多，两个并行，前后一分钟三十来句十秒左右切完。"""


class AppState:
    def __init__(
        self, root: Path, models: tuple[str, ...] = DEFAULT_MODELS, grouping: str = GROUPING_MODEL
    ) -> None:
        self.workspace = load_workspace(root, models, grouping)
        self.store = LabelStore(self.workspace.labels_dir)
        self.lock = threading.RLock()
        self.guesses: dict[int, Guess] = {}
        self.trained: dict[str, Any] = {}
        self._cutting: dict[str, threading.Lock] = {}
        self._prefetch: list[tuple[str, str]] = []
        """等着在后台切的 (种类, 片段)，最近的在前。人换一句就整个换掉。"""
        self._prefetch_ready = threading.Condition()
        self._prefetchers: list[threading.Thread] = []
        self.retrain()

    # 模型

    def retrain(self) -> None:
        """每个目标角色的正例是标成 TA 的片段；反例是标成别的名字的、标「其他」时 TA 已经是
        目标的，以及人说过不是 TA 的。标了「质量低」的不进训练。"""
        targets = self.store.targets()
        examples: dict[str, tuple[list[int], list[int]]] = {t: ([], []) for t in targets}
        used: set[int] = set()
        for clip_id, name in self.store.labels.items():
            clip = self.workspace.by_id.get(clip_id)
            if clip is None or clip.row is None or clip_id in self.store.unusable:
                continue
            against = self.store.against.get(clip_id, set())
            for target in targets:
                if name == target:
                    examples[target][0].append(clip.row)
                elif name != OTHER or target in against:
                    examples[target][1].append(clip.row)
                else:
                    continue
                used.add(clip.row)
        rejects: dict[int, set[str]] = {}
        for clip_id, rejected in self.store.rejects.items():
            clip = self.workspace.by_id.get(clip_id)
            if clip is None or clip.row is None or not rejected:
                continue
            rejects[clip.row] = set(rejected)
            if clip_id in self.store.unusable:
                continue
            for target in rejected & set(targets):
                if self.store.labels.get(clip_id) != target:
                    examples[target][1].append(clip.row)
                    used.add(clip.row)
        began = time.perf_counter()
        trained = train_and_predict(self.workspace.features, examples, rejects)
        self.guesses = trained.guesses
        self.trained = {
            "labels": len(used),
            "roles": len(targets),
            "seconds": round(time.perf_counter() - began, 2),
            "familiar_threshold": trained.threshold,
        }

    # 视图

    def status(self, clip: Clip) -> str:
        if clip.id in self.store.labels:
            return "confirmed"
        if clip.skipped:
            return "skipped"
        if clip.row is None:
            return "novoice"
        guess = self.guesses.get(clip.row)
        if guess is None:
            return "unlabeled"
        return (
            "auto" if guess.confidence >= AUTO_CONFIDENCE and guess.familiar is True else "review"
        )

    def view(self, clip: Clip) -> dict[str, Any]:
        guess = self.guesses.get(clip.row) if clip.row is not None else None
        return {
            "id": clip.id,
            "episode": clip.episode,
            "start": round(clip.start, 3),
            "end": round(clip.end, 3),
            "duration": round(clip.duration, 2),
            "gap": None if clip.gap is None else round(clip.gap, 2),
            "text": clip.text,
            "scene": clip.scene,
            "voiced": clip.row is not None,
            "label": self.store.labels.get(clip.id),
            "rejects": sorted(self.store.rejects.get(clip.id, ())),
            "unusable": clip.id in self.store.unusable,
            "guess": [
                {"name": n, "p": p} for n, p in zip(guess.names, guess.probabilities, strict=True)
            ]
            if guess
            else [],
            "familiar": guess.familiar if guess else None,
            "status": self.status(clip),
        }

    def summary(self) -> dict[str, Any]:
        per_episode: dict[str, Counter[str]] = {e: Counter() for e in self.workspace.episodes}
        confirmed: Counter[str] = Counter()
        predicted: Counter[str] = Counter()
        seconds: defaultdict[str, float] = defaultdict(float)
        low_seconds: defaultdict[str, float] = defaultdict(float)
        for clip in self.workspace.clips:
            state = self.status(clip)
            per_episode[clip.episode][state] += 1
            label = self.store.labels.get(clip.id)
            if state == "confirmed" and label:
                confirmed[label] += 1
                seconds[label] += clip.duration
                if clip.id in self.store.unusable:
                    low_seconds[label] += clip.duration
            elif state in ("auto", "review") and clip.row is not None:
                predicted[self.guesses[clip.row].names[0]] += 1

        def counts(name: str) -> dict[str, Any]:
            """确认过几句、机器归给几句，确认过的共多少秒、其中标了「质量低」的多少秒。"""
            return {
                "confirmed": confirmed[name],
                "predicted": predicted[name],
                "seconds": round(seconds[name], 1),
                "low_seconds": round(low_seconds[name], 1),
            }

        # 目标角色一直列着，哪怕还没有一句；不再是目标的角色有标签时也列着，好再加回来。
        roles = [
            {**role, **counts(role["name"])}
            for role in self.store.roles
            if role.get("target") or confirmed[role["name"]]
        ]
        roles.sort(key=lambda r: (not r.get("target"), -(r["confirmed"] + r["predicted"])))
        return {
            "episodes": [
                {
                    "name": name,
                    "video": bool(meta.get("video")),
                    "counts": dict(per_episode[name]),
                    "text_subtitles": _text_subtitles(meta),
                }
                for name, meta in self.workspace.episodes.items()
            ],
            "workspace": str(self.workspace.root.resolve()),
            "skipped": self.workspace.skipped,
            "roles": roles,
            "other": counts(OTHER),
            "model": {**self.trained, "auto_confidence": AUTO_CONFIDENCE},
            "can_undo": self.store.can_undo(),
        }

    # 改动

    def _snapshot(self) -> dict[str, tuple[str, str | None]]:
        out = {}
        for clip in self.workspace.clips:
            guess = self.guesses.get(clip.row) if clip.row is not None else None
            out[clip.id] = (self.status(clip), guess.names[0] if guess else None)
        return out

    def change(self, batch_maker: Any) -> dict[str, Any]:
        """执行一次改动并重训，返回直接改到的片段、连带变了预测的片段，以及新的总览。"""
        with self.lock:
            before = self._snapshot()
            batch = batch_maker()
            if batch is None:
                return {"batch": None, "updated": [], "ripple": 0, "state": self.summary()}
            self.retrain()
            after = self._snapshot()
            touched = {c["clip"] for c in batch["changes"]}
            moved = [i for i in after if after[i] != before[i] and i not in touched]
            return {
                "batch": batch["batch"],
                "undo": batch.get("undo_of") is not None,
                "updated": [self.view(self.workspace.by_id[i]) for i in [*touched, *moved]
                            if i in self.workspace.by_id],
                "ripple": len(moved),
                "state": self.summary(),
            }  # fmt: skip

    # 起步分组

    def groups(self, episode: str | None) -> list[dict[str, Any]]:
        from sklearn.cluster import AgglomerativeClustering

        pool = [
            c
            for c in self.workspace.clips
            if c.row is not None
            and not c.skipped
            and self.store.labels.get(c.id) is None
            and (episode is None or c.episode == episode)
        ]
        if len(pool) < 2:
            return []
        vectors = self.workspace.grouping[[c.row for c in pool]]
        found = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=GROUP_THRESHOLD,
        ).fit_predict(vectors)
        members: dict[int, list[Clip]] = {}
        for clip, group in zip(pool, found, strict=True):
            members.setdefault(int(group), []).append(clip)
        result: list[dict[str, Any]] = []
        for clips in members.values():
            if len(clips) < 2:
                continue
            clips.sort(key=lambda c: (c.episode, c.start))
            hints = Counter(
                self.guesses[c.row].names[0]
                for c in clips
                if c.row in self.guesses and self.guesses[c.row].names[0] != OTHER
            ).most_common(1)
            result.append(
                {
                    "size": len(clips),
                    "seconds": round(sum(c.duration for c in clips), 1),
                    "hint": {"name": hints[0][0], "share": round(hints[0][1] / len(clips), 2)}
                    if hints
                    else None,
                    "clips": [self.view(c) for c in clips],
                }
            )
        result.sort(key=lambda g: -len(g["clips"]))
        return result

    def role_clips(self, role: str) -> list[dict[str, Any]]:
        """角色视图：确认过的、机器归给 TA 的，再加「可能漏掉的」（`maybe`）。

        可能漏掉的是机器没归给 TA、但「是 TA」的概率不低的片段：还没标的，以及标「其他」时
        TA 还不是目标角色的。加了新的目标角色以后，从这里把以前的「其他」复查一遍。
        「其他」没有可能漏掉的：机器没归给其他的，就归给了某个目标角色，在那个角色里核对。
        「其他」确认过的从最像某个目标角色的排起，标错的先看到；只在取列表时排一次，标完不跳。
        """
        mine, maybe = [], []
        for clip in self.workspace.clips:
            label = self.store.labels.get(clip.id)
            if label == role:
                mine.append(self.view(clip))
                continue
            guess = self.guesses.get(clip.row) if clip.row is not None else None
            if guess is None or role in self.store.rejects.get(clip.id, ()):
                continue
            if label is None and clip.skipped:
                continue
            unchecked = label is None or (
                label == OTHER and role not in self.store.against.get(clip.id, ())
            )
            if label is None and guess.names[0] == role:
                mine.append(self.view(clip))
            elif role != OTHER and unchecked and guess.p(role) >= MAYBE_FLOOR:
                maybe.append((guess.p(role), clip))
        maybe.sort(key=lambda pair: -pair[0])
        if role == OTHER:
            mine.sort(
                key=lambda c: -max((g["p"] for g in c["guess"] if g["name"] != OTHER), default=0)
            )
        return mine + [{**self.view(c), "maybe": True} for _, c in maybe[:MAYBE_LIMIT]]

    def references(self, name: str) -> list[dict[str, Any]]:
        """这个角色最适合当参考音的几条：人确认过、长度在 1.5 到 6 秒之间的优先。"""
        own = [
            c
            for c in self.workspace.clips
            if self.store.labels.get(c.id) == name and c.row is not None
        ]
        own.sort(key=lambda c: (not 1.5 <= c.duration <= 6.0, -c.duration))
        return [self.view(c) for c in own[:3]]

    # 媒体

    def media(self, kind: str, clip_id: str, context: int = 0) -> Path:
        """切好并返回一句的画面或人声。`context` 不为 0 时前后各多放这么多秒（只能是
        `CONTEXT_SECONDS` 里的值），画面和人声从同一时刻开始，另存一份，不碰平时那份。"""
        clip = self.workspace.by_id.get(clip_id)
        if clip is None or not SAFE_ID.fullmatch(clip_id) or context not in (0, *CONTEXT_SECONDS):
            raise KeyError(clip_id)
        episode = self.workspace.episodes[clip.episode]
        folder = Path(episode["directory"]) / "app_media" / kind
        suffix = f".ctx{context}" if context else ""
        target = folder / f"{clip_id}{suffix}.{'wav' if kind == 'audio' else 'mp4'}"
        if target.exists():
            return target
        with self.lock:
            lock = self._cutting.setdefault(clip_id + kind + suffix, threading.Lock())
        with lock:
            if target.exists():
                return target
            folder.mkdir(parents=True, exist_ok=True)
            if kind == "audio":
                start = max(0.0, clip.start - context)
                _cut_audio(Path(episode["vocals"]), start, clip.end + context, target)
            else:
                video = episode.get("video")
                if not video:
                    raise FileNotFoundError("这一集没有视频")
                pad = context or VIDEO_PAD
                cut_video(Path(video), clip.start - pad, clip.end + pad, target)
        return target

    def prefetch(self, clip_id: str, seconds: float = PREFETCH_SECONDS) -> int:
        """把同一集的台词排进后台去切，视频和人声都切：先切这句前后 `seconds` 秒内的，离这句近的
        先切，再按时间往后切到这一集结束。已经切好的不排。换一句就换掉整个队列，所以快速翻过去的
        那些句不会白占时间。返回排了几段。"""
        clip = self.workspace.by_id.get(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        episode = self.workspace.episodes[clip.episode]
        kinds = ("video", "audio") if episode.get("video") else ("audio",)
        folder = Path(episode["directory"]) / "app_media"
        same = [c for c in self.workspace.clips if c.episode == clip.episode]
        near = [c for c in same if c.end >= clip.start - seconds and c.start <= clip.end + seconds]
        near.sort(key=lambda c: abs(c.start - clip.start))
        taken = {c.id for c in near}
        later = sorted(
            (c for c in same if c.start > clip.start and c.id not in taken), key=lambda c: c.start
        )
        jobs = [
            (kind, c.id)
            for c in near + later
            for kind in kinds
            if not (folder / kind / f"{c.id}.{'wav' if kind == 'audio' else 'mp4'}").exists()
        ]
        with self._prefetch_ready:
            self._prefetch = jobs
            while len(self._prefetchers) < PREFETCH_WORKERS:
                worker = threading.Thread(target=self._prefetch_loop, daemon=True)
                worker.start()
                self._prefetchers.append(worker)
            self._prefetch_ready.notify_all()
        return len(jobs)

    def _prefetch_loop(self) -> None:
        while True:
            with self._prefetch_ready:
                while not self._prefetch:
                    self._prefetch_ready.wait()
                kind, clip_id = self._prefetch.pop(0)
            # 切不了的等人真点到那句时再报错。
            with contextlib.suppress(KeyError, FileNotFoundError, ValueError):
                self.media(kind, clip_id)

    def save_avatar(self, name: str, data_url: str) -> dict[str, Any]:
        head, _, body = data_url.partition(",")
        if head not in ("data:image/jpeg;base64", "data:image/png;base64"):
            raise ValueError("头像只收 JPEG 或 PNG")
        raw = base64.b64decode(body, validate=True)
        if len(raw) > 2_000_000:
            raise ValueError("头像太大")
        file = hashlib.sha256(raw).hexdigest()[:16] + (".jpg" if "jpeg" in head else ".png")
        folder = self.workspace.labels_dir / "avatars"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / file).write_bytes(raw)
        return self.store.update_role(name, avatar=file)

    # 导出

    def set_text_subtitles(self, episode: str, path: Path) -> dict[str, Any]:
        from avs.pipeline import attach_text_subtitles

        meta = self.workspace.episodes.get(episode)
        if meta is None:
            raise ValueError(f"没有 {episode} 这一集")
        result = attach_text_subtitles(Path(meta["directory"]), path)
        meta.update({k: v for k, v in result.items() if k.startswith("text_subtitle")})
        return result

    def _retext(
        self, assigned: dict[str, list[Clip]]
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """导出的台词换成另配字幕的文字。返回（片段 ID 到文字, 不收的片段）。"""
        from avs.stages.text_subtitle import load_text_lines, match, own_tag, shifted, touching

        needed = sorted({c.episode for clips in assigned.values() for c in clips})
        missing = [e for e in needed if not self.workspace.episodes[e].get("text_subtitles")]
        if missing:
            raise ValueError(
                f"{'、'.join(missing)} 还没配台词字幕，先在下面配上，或者改用原字幕的文字"
            )
        lines = {}
        for name in needed:
            meta = self.workspace.episodes[name]
            path = Path(meta["text_subtitles"])
            if not path.is_file():
                raise ValueError(f"{name} 配的台词字幕不见了：{path}")
            lines[name] = shifted(load_text_lines(path), float(meta["text_subtitle_offset"]))
        texts: dict[str, str] = {}
        rejected: list[dict[str, Any]] = []
        for role, clips in assigned.items():
            tag = own_tag(x for c in clips for x in touching(lines[c.episode], c.start, c.end))
            kept = []
            for clip in clips:
                text, reason = match(lines[clip.episode], clip.start, clip.end, tag)
                if reason is None:
                    texts[clip.id] = text
                    kept.append(clip)
                else:
                    rejected.append({"role": role, "clip": clip, "reason": reason, "text": text})
            clips[:] = kept
        return texts, rejected

    def export(self, roles: list[str], include_auto: bool, form: str, language: str,
               out: Path, text_subtitles: bool = False) -> dict[str, Any]:  # fmt: skip
        from avs.stages.export import export, summarize

        if form not in ("gpt-sovits", "style-bert-vits2", "folder"):
            raise ValueError("不认识的导出格式")
        if out.exists() and any(out.iterdir()):
            raise ValueError(f"{out} 已存在且不是空的，换一个目录")
        assigned: dict[str, list[Clip]] = {name: [] for name in roles}
        rejected: list[dict[str, Any]] = []
        for clip in self.workspace.clips:
            label = self.store.labels.get(clip.id)
            state = self.status(clip)
            role = None
            if state == "confirmed" and label in assigned:
                role = label
            elif include_auto and state == "auto" and clip.row is not None:
                top = self.guesses[clip.row].names[0]
                role = top if top in assigned else None
            if role is None:
                continue
            if clip.id in self.store.unusable:
                rejected.append({"role": role, "clip": clip, "reason": UNUSABLE, "text": ""})
            else:
                assigned[role].append(clip)
        if not any(assigned.values()):
            raise ValueError(
                f"没有可导出的片段：{len(rejected)} 条都标了质量低"
                if rejected
                else "没有可导出的片段"
            )
        texts = {c.id: c.text for c in self.workspace.clips}
        if text_subtitles and form != "folder":
            texts, unmatched = self._retext(assigned)
            rejected += unmatched
            if not any(assigned.values()):
                raise ValueError(f"{len(unmatched)} 条片段全都对不上台词字幕，一条也没导出")
        vocals = {name: Path(meta["vocals"]) for name, meta in self.workspace.episodes.items()}
        written = export({k: v for k, v in assigned.items() if v}, vocals, out)
        by_span = {
            (c.episode, round(c.start, 6), round(c.end, 6)): c.id for c in self.workspace.clips
        }
        lines = []
        for item in written:
            clip_id = by_span.get((item.episode, round(item.start, 6), round(item.end, 6)))
            text = texts.get(clip_id, "") if clip_id else ""
            text = text.replace("|", " ").replace("\n", " ")
            if form == "gpt-sovits":
                lines.append(f"{item.path.resolve()}|{item.name}|{language}|{text}")
            elif form == "style-bert-vits2":
                rel = item.path.relative_to(out).as_posix()
                lines.append(f"{rel}|{item.name}|{language.upper()[:2]}|{text}")
        if lines:
            listing = out / ("esd.list" if form == "style-bert-vits2" else "train.list")
            listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if rejected:
            _write_rejected(out / "rejected.tsv", rejected)
        reasons = Counter(r["reason"] for r in rejected)
        return {"out": str(out.resolve()), **summarize(written), "rejected": dict(reasons)}


class LabelBody(BaseModel):
    clips: list[str]
    label: str | None = None
    """角色名或「其他」；空表示清掉标签。"""
    new_role: bool = False
    """标成一个新建的、还没起名字的角色，这时 `label` 不用给。"""
    unusable: bool = False
    """同时标「质量低」。只对目标角色有效；标成别的、或清掉标签时一律关掉。"""


class PrefetchBody(BaseModel):
    clip: str


class ChangesBody(BaseModel):
    changes: list[dict[str, Any]]


class RoleBody(BaseModel):
    name: str
    new_name: str | None = None
    color: str | None = None
    target: bool | None = None


class AvatarBody(BaseModel):
    name: str
    image: str
    """data URL 形式的 JPEG 或 PNG。"""


class ExportBody(BaseModel):
    roles: list[str]
    include_auto: bool = False
    form: str = "gpt-sovits"
    language: str = "ja"
    out: str
    text_subtitles: bool = False
    """台词文字从每集另配的字幕里取，而不是切片段用的那份。"""


class TextSubtitlesBody(BaseModel):
    episode: str
    path: str


def _text_subtitles(meta: dict[str, Any]) -> dict[str, Any] | None:
    """一集另配的台词字幕，给界面显示。"""
    if not meta.get("text_subtitles"):
        return None
    return {
        "file": Path(meta["text_subtitles"]).name,
        "offset": meta.get("text_subtitle_offset"),
        "agreement": meta.get("text_subtitle_agreement"),
    }


def _write_rejected(path: Path, rejected: list[dict[str, Any]]) -> None:
    """对不上台词字幕、没导出的片段，一行一条，好回界面里找。"""
    rows = ["角色\t集\t开始\t结束\t原因\t原字幕\t台词字幕"]
    for item in rejected:
        clip = item["clip"]
        cells = [item["role"], clip.episode, f"{clip.start:.2f}", f"{clip.end:.2f}",
                 item["reason"], clip.text, item["text"]]  # fmt: skip
        rows.append("\t".join(c.replace("\t", " ").replace("\n", " ") for c in cells))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _cut_audio(vocals: Path, start: float, end: float, target: Path) -> None:
    import soundfile as sf

    rate = sf.info(str(vocals)).samplerate
    wave, _ = sf.read(str(vocals), start=int(start * rate), stop=int(end * rate), always_2d=True)
    temporary = target.with_suffix(".part.wav")
    sf.write(str(temporary), wave, rate, subtype="PCM_16")
    temporary.replace(target)


def create_app(state: AppState) -> Any:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="avs", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def always_check_page_files(request: Any, call_next: Any) -> Any:
        """网页和样式、脚本每次都向服务端核对一下（没改过只回 304）。不加这个头，浏览器会凭
        修改时间自己缓存一阵，改了界面以后刷新，可能还在用旧的样式或脚本。"""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    def clips_where(keep: Any) -> list[dict[str, Any]]:
        return [state.view(c) for c in state.workspace.clips if keep(c)]

    @app.get("/api/state")
    def read_state() -> dict[str, Any]:
        with state.lock:
            return state.summary()

    @app.get("/api/clips")
    def read_clips(episode: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        with state.lock:
            if role is not None:
                return state.role_clips(role)
            return clips_where(lambda c: episode is None or c.episode == episode)

    @app.get("/api/groups")
    def read_groups(episode: str | None = None) -> list[dict[str, Any]]:
        with state.lock:
            return state.groups(episode)

    @app.get("/api/references")
    def read_references(name: str) -> list[dict[str, Any]]:
        with state.lock:
            return state.references(name)

    @app.post("/api/label")
    def post_label(body: LabelBody) -> dict[str, Any]:
        unknown = [c for c in body.clips if c not in state.workspace.by_id]
        if unknown or not body.clips:
            raise HTTPException(400, "片段不存在")
        with state.lock:
            label = state.store.new_role() if body.new_role else (body.label or "").strip() or None
            cast = {"unnamed": [label]} if body.new_role else None
            # 一次选择就定下「是谁」和「质量低」：标成干净的就把以前的「质量低」关掉。
            changes: list[dict[str, Any]] = [{"clip": c, "label": label} for c in body.clips]
            role = state.store.role(label) if label else None
            # 新名字会建成目标角色，所以没在角色表里的也算。
            unusable = (
                body.unusable
                and label is not None
                and label != OTHER
                and (role is None or bool(role.get("target")))
            )
            changes += [{"clip": c, "unusable": unusable} for c in body.clips]
            return {"role": label, **state.change(lambda: state.store.apply(changes, cast=cast))}

    @app.post("/api/changes")
    def post_changes(body: ChangesBody) -> dict[str, Any]:
        """一批混合的改动，整批记一次、整批撤销。角色视图「确认其余」和「质量低」
        都走这里。"""
        clean = []
        for change in body.changes:
            if change.get("clip") not in state.workspace.by_id:
                raise HTTPException(400, "片段不存在")
            if "reject" in change:
                clean.append(
                    {
                        "clip": change["clip"],
                        "reject": str(change["reject"]),
                        "on": bool(change["on"]),
                    }
                )
            elif (flag := flag_of(change)) is not None:
                on = next(v for k, v in change.items() if OLD_FLAGS.get(k, k) == flag)
                clean.append({"clip": change["clip"], flag: bool(on)})
            elif "label" in change:
                clean.append({"clip": change["clip"], "label": change["label"]})
            else:
                raise HTTPException(400, "不认识的改动")
        return state.change(lambda: state.store.apply(clean))

    @app.post("/api/undo")
    def post_undo() -> dict[str, Any]:
        return state.change(state.store.undo)

    @app.post("/api/roles")
    def post_role(body: RoleBody) -> dict[str, Any]:
        try:
            if body.new_name is not None:
                new_name = body.new_name
                return state.change(lambda: state.store.rename_role(body.name, new_name))
            state.store.update_role(body.name, color=body.color, target=body.target)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with state.lock:
            state.retrain()
            return {"batch": None, "updated": [], "ripple": 0, "state": state.summary()}

    @app.post("/api/roles/avatar")
    def post_avatar(body: AvatarBody) -> dict[str, Any]:
        try:
            state.save_avatar(body.name, body.image)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with state.lock:
            return state.summary()

    @app.post("/api/export")
    def post_export(body: ExportBody) -> dict[str, Any]:
        try:
            with state.lock:
                return state.export(
                    body.roles,
                    body.include_auto,
                    body.form,
                    body.language,
                    Path(body.out),
                    body.text_subtitles,
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/text-subtitles")
    def post_text_subtitles(body: TextSubtitlesBody) -> dict[str, Any]:
        try:
            with state.lock:
                state.set_text_subtitles(body.episode, Path(body.path.strip().strip('"')))
                return state.summary()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # 头像的路由要排在 /media/{kind}/{clip_id} 前面，否则 avatar 会被当成 kind 拦下来。
    @app.get("/media/avatar/{file}")
    def read_avatar(file: str) -> Any:
        path = state.workspace.labels_dir / "avatars" / file
        if not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png)", file) or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/media/{kind}/{clip_id}")
    def read_media(kind: str, clip_id: str, context: int = 0) -> Any:
        clip_id = clip_id.rsplit(".", 1)[0]
        if kind not in ("audio", "video"):
            raise HTTPException(404)
        try:
            return FileResponse(state.media(kind, clip_id, context))
        except KeyError as exc:
            raise HTTPException(404) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/prefetch")
    def post_prefetch(body: PrefetchBody) -> dict[str, Any]:
        """人看到一句时网页调这个，后台先切好前后一分钟的片段。"""
        try:
            return {"queued": state.prefetch(body.clip)}
        except KeyError as exc:
            raise HTTPException(404) from exc

    @app.get("/favicon.ico")
    def favicon() -> Any:
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    @app.get("/")
    def index() -> Any:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
