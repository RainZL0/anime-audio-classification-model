"""本地服务：给网页提供片段、预测和媒体，接收标注，每次标注后重训。

只监听 127.0.0.1。状态都在内存里，改动先写进标签记录再更新内存，进程崩了重开就能接着用。
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from avs.app.labels import LabelStore, is_special
from avs.app.model import AUTO_CONFIDENCE, Guess, train_and_predict
from avs.app.workspace import DEFAULT_MODELS, GROUPING_MODEL, Clip, load_workspace
from avs.labeling import SPECIAL, VIDEO_PAD, cut_video

STATIC = Path(__file__).parent / "static"
GROUP_THRESHOLD = 0.70
"""起步分组用 anime-va 的分界线，见 docs/DECISIONS.md。"""
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


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
        self.retrain()

    # 模型

    def retrain(self) -> None:
        rows, names = [], []
        for clip_id, name in self.store.labels.items():
            clip = self.workspace.by_id.get(clip_id)
            if clip is None or clip.row is None or is_special(name):
                continue
            if self.store.trainable(name):
                rows.append(clip.row)
                names.append(name)
        rejects: dict[int, set[str]] = {}
        for clip_id, rejected in self.store.rejects.items():
            clip = self.workspace.by_id.get(clip_id)
            if clip is not None and clip.row is not None and rejected:
                rejects[clip.row] = set(rejected)
        began = time.perf_counter()
        trained = train_and_predict(self.workspace.features, rows, names, rejects)
        self.guesses = trained.guesses
        self.trained = {
            "labels": len(rows),
            "roles": len(set(names)),
            "seconds": round(time.perf_counter() - began, 2),
            "familiar_threshold": trained.threshold,
        }

    # 视图

    def status(self, clip: Clip) -> str:
        label = self.store.labels.get(clip.id)
        if label is not None:
            return "special" if is_special(label) else "confirmed"
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
            "text": clip.text,
            "scene": clip.scene,
            "voiced": clip.row is not None,
            "label": self.store.labels.get(clip.id),
            "rejects": sorted(self.store.rejects.get(clip.id, ())),
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
        for clip in self.workspace.clips:
            state = self.status(clip)
            per_episode[clip.episode][state] += 1
            label = self.store.labels.get(clip.id)
            if state == "confirmed" and label:
                confirmed[label] += 1
            elif state in ("auto", "review") and clip.row is not None:
                predicted[self.guesses[clip.row].names[0]] += 1
        roles = [
            {**role, "confirmed": confirmed[role["name"]], "predicted": predicted[role["name"]]}
            for role in self.store.roles
            if confirmed[role["name"]] or predicted[role["name"]]
        ]
        roles.sort(key=lambda r: -(r["confirmed"] + r["predicted"]))
        return {
            "episodes": [
                {"name": name, "video": bool(meta.get("video")), "counts": dict(per_episode[name])}
                for name, meta in self.workspace.episodes.items()
            ],
            "roles": roles,
            "special": SPECIAL,
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
                self.guesses[c.row].names[0] for c in clips if c.row in self.guesses
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

    def media(self, kind: str, clip_id: str) -> Path:
        clip = self.workspace.by_id.get(clip_id)
        if clip is None or not SAFE_ID.fullmatch(clip_id):
            raise KeyError(clip_id)
        episode = self.workspace.episodes[clip.episode]
        folder = Path(episode["directory"]) / "app_media" / kind
        target = folder / f"{clip_id}.{'wav' if kind == 'audio' else 'mp4'}"
        if target.exists():
            return target
        with self.lock:
            lock = self._cutting.setdefault(clip_id + kind, threading.Lock())
        with lock:
            if target.exists():
                return target
            folder.mkdir(parents=True, exist_ok=True)
            if kind == "audio":
                _cut_audio(Path(episode["vocals"]), clip.start, clip.end, target)
            else:
                video = episode.get("video")
                if not video:
                    raise FileNotFoundError("这一集没有视频")
                cut_video(Path(video), clip.start - VIDEO_PAD, clip.end + VIDEO_PAD, target)
        return target

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

    def export(self, roles: list[str], include_auto: bool, form: str, language: str,
               out: Path) -> dict[str, Any]:  # fmt: skip
        from avs.stages.export import export, summarize

        if form not in ("gpt-sovits", "style-bert-vits2", "folder"):
            raise ValueError("不认识的导出格式")
        if out.exists() and any(out.iterdir()):
            raise ValueError(f"{out} 已存在且不是空的，换一个目录")
        assigned: dict[str, list[Clip]] = {name: [] for name in roles}
        for clip in self.workspace.clips:
            label = self.store.labels.get(clip.id)
            state = self.status(clip)
            if state == "confirmed" and label in assigned:
                assigned[label].append(clip)
            elif include_auto and state == "auto" and clip.row is not None:
                top = self.guesses[clip.row].names[0]
                if top in assigned:
                    assigned[top].append(clip)
        vocals = {name: Path(meta["vocals"]) for name, meta in self.workspace.episodes.items()}
        written = export({k: v for k, v in assigned.items() if v}, vocals, out)
        texts = {
            (c.episode, round(c.start, 6), round(c.end, 6)): c.text for c in self.workspace.clips
        }
        lines = []
        for item in written:
            text = texts.get((item.episode, round(item.start, 6), round(item.end, 6)), "")
            text = text.replace("|", " ").replace("\n", " ")
            if form == "gpt-sovits":
                lines.append(f"{item.path.resolve()}|{item.name}|{language}|{text}")
            elif form == "style-bert-vits2":
                rel = item.path.relative_to(out).as_posix()
                lines.append(f"{rel}|{item.name}|{language.upper()[:2]}|{text}")
        if lines:
            listing = out / ("esd.list" if form == "style-bert-vits2" else "train.list")
            listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"out": str(out.resolve()), **summarize(written)}


class LabelBody(BaseModel):
    clips: list[str]
    label: str | None = None
    """角色名或特殊标签；空表示清掉标签。"""


class ChangesBody(BaseModel):
    changes: list[dict[str, Any]]


class RoleBody(BaseModel):
    name: str
    new_name: str | None = None
    color: str | None = None
    trainable: bool | None = None


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

                def mine(c: Clip) -> bool:
                    label = state.store.labels.get(c.id)
                    if label is not None:
                        return label == role
                    guess = state.guesses.get(c.row) if c.row is not None else None
                    return guess is not None and guess.names[0] == role

                return clips_where(mine)
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
        changes = [{"clip": c, "label": body.label} for c in body.clips]
        return state.change(lambda: state.store.apply(changes))

    @app.post("/api/changes")
    def post_changes(body: ChangesBody) -> dict[str, Any]:
        """一批混合的改动，整批记一次、整批撤销。角色视图「确认其余、剔除标出的」用它。"""
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
            else:
                clean.append({"clip": change["clip"], "label": change.get("label")})
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
            state.store.update_role(body.name, color=body.color, trainable=body.trainable)
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
                    body.roles, body.include_auto, body.form, body.language, Path(body.out)
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/media/{kind}/{clip_id}")
    def read_media(kind: str, clip_id: str) -> Any:
        clip_id = clip_id.rsplit(".", 1)[0]
        if kind not in ("audio", "video"):
            raise HTTPException(404)
        try:
            return FileResponse(state.media(kind, clip_id))
        except KeyError as exc:
            raise HTTPException(404) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/media/avatar/{file}")
    def read_avatar(file: str) -> Any:
        path = state.workspace.labels_dir / "avatars" / file
        if not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png)", file) or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/favicon.ico")
    def favicon() -> Any:
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    @app.get("/")
    def index() -> Any:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
