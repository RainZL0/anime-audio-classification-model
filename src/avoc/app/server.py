"""Local server: gives the web page clips, predictions and media, takes in labels, and retrains
after each label.

Listens only on 127.0.0.1. State is kept in memory. Each change is written to the label records
first, then memory is updated. If the process crashes, restarting it picks up where it left off.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from avoc.app.adding import Adding, clean_path
from avoc.app.labels import OLD_FLAGS, OTHER, LabelStore, flag_of
from avoc.app.model import AUTO_CONFIDENCE, MIN_GUESS_LABELS, Guess, train_and_predict
from avoc.app.video import VIDEO_PAD, cut_video
from avoc.app.workspace import DEFAULT_MODELS, GROUPING_MODEL, Clip, load_workspace
from avoc.language import LANGUAGE, Words, say
from avoc.project import read_json, write_json
from avoc.stages.captions import marked_note

STATIC = Path(__file__).parent / "static"
PURPOSES = ("tts", "audio")
"""What the voices can be collected for; see `AppState.purpose`."""
GROUP_THRESHOLD = 0.70
"""The Groups view uses anime-va's threshold. See docs/DECISIONS.md."""
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
MAYBE_FLOOR = 0.05
"""The "possibly missed" list in the Characters view only includes clips whose chance of being the
target is at least this number."""
UNUSABLE = Words("人标了质量低", "marked low quality")
"""Why a clip someone marked low quality was skipped on export, as written in rejected.tsv."""
MAYBE_LIMIT = 100
"""The "possibly missed" list shows at most this many clips, most likely first."""
CONTEXT_SECONDS = (5, 15)
"""When it is hard to tell who is speaking, the clip can be temporarily extended by this many
seconds before and after. Press L to step through the options. Only cut when the person asks."""
PREFETCH_SECONDS = 60.0
"""When one line is shown, first cut the dialogue clips within this many seconds before and after it
in the background, so jumping nearby does not wait. Then keep cutting the later ones."""
PREFETCH_WORKERS = 2
"""How many clips to cut at the same time in the background. Cutting one picture takes half a second
or more. With two running in parallel, about thirty lines before and after, within one minute, get
cut in about ten seconds."""


def _code_stamp() -> float:
    """When the program's own Python files last changed. The page files are read from disk on
    every request, so after an update (git pull) a running server would serve the new page with
    its old code; comparing this stamp with the one at start tells the page to ask for a
    restart."""
    return max(p.stat().st_mtime for p in Path(__file__).parents[1].rglob("*.py"))


class AppState:
    def __init__(
        self, root: Path, models: tuple[str, ...] = DEFAULT_MODELS, grouping: str = GROUPING_MODEL
    ) -> None:
        self.models, self.grouping_model = models, grouping
        self.code_stamp = _code_stamp()
        self.workspace = load_workspace(root, models, grouping)
        self.store = LabelStore(self.workspace.labels_dir)
        self.adding = Adding(root, lambda _: self.reload())
        self.adding.drop_records(set(self.workspace.episodes))
        self.lock = threading.RLock()
        self.guesses: dict[int, Guess] = {}
        self.trained: dict[str, Any] = {}
        self.tags: dict[str, str | None] = {}
        self._cutting: dict[str, threading.Lock] = {}
        self._prefetch: list[tuple[str, str]] = []
        """The (kind, clip) pairs waiting to be cut in the background, nearest first. Each time the
        person moves to another line, the whole list is replaced."""
        self._prefetch_ready = threading.Condition()
        self._prefetchers: list[threading.Thread] = []
        self.retrain()

    def reload(self) -> None:
        """Load the workspace again after an episode was added. Labels are kept as they are."""
        workspace = load_workspace(self.workspace.root, self.models, self.grouping_model)
        with self.lock:
            self.workspace = workspace
            self.retrain()
        self.adding.drop_records(set(workspace.episodes))

    # Model

    def retrain(self) -> None:
        """Positive examples for each target character are clips labeled as them. Negative
        examples are clips labeled with other names, clips labeled "other" while that character
        was already a target, and clips the person said are not them. Clips marked "low quality"
        are not used in training."""
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
        trained = train_and_predict(self.workspace.features, examples, rejects, MIN_GUESS_LABELS)
        self.guesses = trained.guesses
        self.trained = {
            "labels": len(used),
            "roles": len(targets),
            "seconds": round(time.perf_counter() - began, 2),
            "familiar_threshold": trained.threshold,
            "min_labels": MIN_GUESS_LABELS,
            # Targets the machine does not guess yet, with what it has of them so far.
            "waiting": {
                t: {"lines": len(pos), "others": len(neg)}
                for t, (pos, neg) in examples.items()
                if len(pos) < MIN_GUESS_LABELS or not neg
            },
        }
        self._find_tags(set(targets))

    def _find_tags(self, targets: set[str]) -> None:
        """Each target character's name in the subtitles, from the lines their clips touch. It
        tells their lines from someone else's in a clip; see `own_tag`."""
        from avoc.stages.text_subtitle import own_tag

        hits: dict[str, list[Any]] = {t: [] for t in targets}
        for clip in self.workspace.clips:
            role = self.role_of(clip, targets)
            if role is not None and clip.spoken_hits:
                hits[role].extend(clip.spoken_hits)
        self.tags = {role: own_tag(found) for role, found in hits.items()}

    def role_of(self, clip: Clip, targets: set[str] | None = None) -> str | None:
        """The target character a clip belongs to, by a person's label or else the machine's top
        guess. None for "other" and for clips nobody has an answer for."""
        targets = set(self.store.targets()) if targets is None else targets
        label = self.store.labels.get(clip.id)
        if label is not None:
            return label if label in targets else None
        guess = self.guesses.get(clip.row) if clip.row is not None else None
        return guess.names[0] if guess and guess.names[0] in targets else None

    def spoken_of(self, clip: Clip, role: str | None) -> tuple[str, str | None]:
        """The clip's text in the spoken language, and why it cannot be exported (None if it
        can). `role` picks whose name in the subtitles counts as their own."""
        return self.text_of(clip, self.tags.get(role) if role else None)

    def text_of(self, clip: Clip, tag: str | None) -> tuple[str, str | None]:
        """`spoken_of`, with the character's name in the subtitles given (see `own_tag`)."""
        from avoc.stages.text_subtitle import match_hits

        if clip.spoken_hits is None:
            said = self.workspace.spoken.get(clip.episode)
            return "", str(said.problem) if said and said.problem else say("没有台词", "no text")
        return match_hits(clip.spoken_hits, clip.start, clip.end, tag)

    # Views

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
        role = self.role_of(clip)
        spoken, problem = self.spoken_of(clip, role)
        return {
            "spoken": spoken,
            "spoken_problem": problem,
            "role": role,
            "id": clip.id,
            "episode": clip.episode,
            "start": round(clip.start, 3),
            "end": round(clip.end, 3),
            "duration": round(clip.duration, 2),
            "gap": None if clip.gap is None else round(clip.gap, 2),
            "text": clip.text,
            "display": clip.display,
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

    def _unfinished(self, not_cut: list[str]) -> dict[str, str]:
        """Episodes not loaded, and why: ones with clips but not all voiceprints, and ones whose
        clips were never cut, known only from the record of episodes being added."""
        unfinished = {name: str(why) for name, why in self.workspace.skipped.items()}
        for name in not_cut:
            unfinished.setdefault(
                name,
                say(
                    "上次没加完，片段还没切好。接着做要从头切，这一步最慢",
                    "not finished last time, and its clips were never cut. Carrying on starts "
                    "the cutting over, the slowest step",
                ),
            )
        return unfinished

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
            """How many lines were confirmed and how many the machine assigned. Also the total
            seconds of confirmed lines, and the seconds of those marked "low quality"."""
            return {
                "confirmed": confirmed[name],
                "predicted": predicted[name],
                "seconds": round(seconds[name], 1),
                "low_seconds": round(low_seconds[name], 1),
            }

        # Target characters are always listed, even with no lines yet. Characters that are no
        # longer targets are listed too when they have labels, so they can be added back.
        roles = [
            {**role, **counts(role["name"])}
            for role in self.store.roles
            if role.get("target") or confirmed[role["name"]]
        ]
        roles.sort(key=lambda r: (not r.get("target"), -(r["confirmed"] + r["predicted"])))
        blocked = self._blocked()
        not_cut = self.adding.not_cut()
        return {
            "episodes": [
                {
                    "name": name,
                    "video": bool(meta.get("video")),
                    "offset": meta.get("subtitle_offset"),
                    "counts": dict(per_episode[name]),
                    "spoken": self._spoken_summary(name, blocked[name]),
                }
                for name, meta in self.workspace.episodes.items()
            ],
            "workspace": str(self.workspace.root.resolve()),
            "export_folder": str(free_export_folder(self.workspace.root)),
            "skipped": self._unfinished(not_cut),
            "not_cut": not_cut,
            "roles": roles,
            "other": counts(OTHER),
            "model": {**self.trained, "auto_confidence": AUTO_CONFIDENCE},
            "can_undo": self.store.can_undo(),
            "outdated": _code_stamp() > self.code_stamp,
            "purpose": self.purpose(),
        }

    # What the voices are for

    @property
    def _purpose_file(self) -> Path:
        return self.workspace.labels_dir / "purpose.json"

    def purpose(self) -> str | None:
        """What the voices are collected for: "tts" (reading text aloud, so each line's text is
        needed too) or "audio" (sound only). Chosen once, at the start; None until then."""
        path = self._purpose_file
        return read_json(path)["purpose"] if path.exists() else None

    def set_purpose(self, purpose: str) -> None:
        """Record the choice. It is made once: switching midway is not supported yet."""
        if purpose not in PURPOSES:
            raise ValueError(say(f"不认识的用途：{purpose}", f"unknown purpose: {purpose}"))
        chosen = self.purpose()
        if chosen is not None and chosen != purpose:
            raise ValueError(
                say(
                    "收集声音做什么用，开始时已经选定，中途换还不支持",
                    "what the voices are for was chosen at the start; switching midway is not "
                    "supported yet",
                )
            )
        write_json(self._purpose_file, {"purpose": purpose})

    def _blocked(self) -> Counter[str]:
        """Per episode, how many clips of target characters cannot be exported with text."""
        targets = set(self.store.targets())
        blocked: Counter[str] = Counter()
        for clip in self.workspace.clips:
            if role := self.role_of(clip, targets):
                blocked[clip.episode] += self.spoken_of(clip, role)[1] is not None
        return blocked

    def _spoken_summary(self, episode: str, blocked: int) -> dict[str, Any]:
        """The episode's spoken language and where its text comes from."""
        said = self.workspace.spoken[episode]
        return {
            "language": said.language,
            "assumed": said.assumed,
            "source": said.source,
            "problem": str(said.problem) if said.problem else None,
            "blocked": blocked,
        }

    # Changes

    def _snapshot(self) -> dict[str, tuple[str, str | None]]:
        out = {}
        for clip in self.workspace.clips:
            guess = self.guesses.get(clip.row) if clip.row is not None else None
            out[clip.id] = (self.status(clip), guess.names[0] if guess else None)
        return out

    def change(self, batch_maker: Any) -> dict[str, Any]:
        """Make one change and retrain. Returns the clips it changed directly, the clips whose
        predictions changed as a side effect, and the new overview."""
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

    # Groups view

    def groups(self, episode: str | None) -> list[dict[str, Any]]:
        from sklearn.cluster import AgglomerativeClustering

        # Only lines still to do, as in "Only to do" in Scenes: not labeled, not skipped, with a
        # voiceprint, and not a guess the machine is confident about.
        pool = [
            c
            for c in self.workspace.clips
            if (episode is None or c.episode == episode)
            and self.status(c) in ("review", "unlabeled")
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
        """Characters view: clips confirmed for this character, clips the machine assigned to
        them, and the "possibly missed" clips (`maybe`).

        Possibly missed clips are ones the machine did not assign to them, but whose chance of being
        them is not low. These are clips not labeled yet, and clips labeled "other" while that
        character was not yet a target character. After a new target character is added, the
        earlier "other" labels are checked again from here.
        "Other" has no possibly-missed list. A clip the machine did not give to "other" was given to
        some target character, and it is checked within that character.
        Confirmed "other" clips are sorted starting from the ones closest to a target character,
        so wrong labels show up first. Sorting happens once when the list is fetched, so a clip
        does not jump after it is labeled.
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
        """The few clips that work best as reference audio for this character. Clips confirmed by a
        person and between 1.5 and 6 seconds long come first."""
        own = [
            c
            for c in self.workspace.clips
            if self.store.labels.get(c.id) == name and c.row is not None
        ]
        own.sort(key=lambda c: (not 1.5 <= c.duration <= 6.0, -c.duration))
        return [self.view(c) for c in own[:3]]

    # Media

    def media(self, kind: str, clip_id: str, context: int = 0, fresh: bool = False) -> Path:
        """Cut and return the picture or vocals of one line. When `context` is not 0, this many
        seconds are added before and after (only a value from `CONTEXT_SECONDS`). The picture and
        vocals start at the same moment. They are saved as a separate copy, and the normal copy is
        left alone. `fresh` throws away the saved cut first, for when it will not play."""
        clip = self.workspace.by_id.get(clip_id)
        if clip is None or not SAFE_ID.fullmatch(clip_id) or context not in (0, *CONTEXT_SECONDS):
            raise KeyError(clip_id)
        episode = self.workspace.episodes[clip.episode]
        folder = Path(episode["directory"]) / "app_media" / kind
        suffix = f".ctx{context}" if context else ""
        target = folder / f"{clip_id}{suffix}.{'wav' if kind == 'audio' else 'mp4'}"
        if target.exists() and not fresh:
            return target
        with self.lock:
            lock = self._cutting.setdefault(clip_id + kind + suffix, threading.Lock())
        with lock:
            if fresh:
                target.unlink(missing_ok=True)
            if target.exists():
                return target
            folder.mkdir(parents=True, exist_ok=True)
            if kind == "audio":
                start = max(0.0, clip.start - context)
                _cut_audio(Path(episode["vocals"]), start, clip.end + context, target)
            else:
                video = episode.get("video")
                if not video:
                    raise FileNotFoundError(say("这一集没有视频", "this episode has no video"))
                pad = context or VIDEO_PAD
                cut_video(Path(video), clip.start - pad, clip.end + pad, target)
        return target

    def prefetch(self, clip_id: str, seconds: float = PREFETCH_SECONDS) -> int:
        """Queue the dialogue lines of the same episode for background cutting, both video and
        vocals. First cut the ones within `seconds` of this line, nearest first. Then keep cutting
        forward in time to the end of the episode. Lines already cut are not queued. Each time the
        person moves to another line, the whole queue is replaced, so lines flipped past quickly do
        not waste time. Returns how many jobs were queued."""
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
            # If a clip cannot be cut, report the error only when the person clicks that line.
            with contextlib.suppress(KeyError, FileNotFoundError, ValueError):
                self.media(kind, clip_id)

    def save_avatar(self, name: str, data_url: str) -> dict[str, Any]:
        head, _, body = data_url.partition(",")
        if head not in ("data:image/jpeg;base64", "data:image/png;base64"):
            raise ValueError(say("头像只收 JPEG 或 PNG", "the picture must be JPEG or PNG"))
        raw = base64.b64decode(body, validate=True)
        if len(raw) > 2_000_000:
            raise ValueError(say("头像太大", "the picture is too large"))
        file = hashlib.sha256(raw).hexdigest()[:16] + (".jpg" if "jpeg" in head else ".png")
        folder = self.workspace.labels_dir / "avatars"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / file).write_bytes(raw)
        return self.store.update_role(name, avatar=file)

    # Export

    def set_spoken(self, episode: str, code: str) -> dict[str, Any]:
        from avoc.pipeline import set_spoken_language

        meta = self.workspace.episodes.get(episode)
        if meta is None:
            raise ValueError(say(f"没有 {episode} 这一集", f"there is no episode {episode}"))
        result = set_spoken_language(Path(meta["directory"]), code)
        self.reload()
        return result

    def _text_for_export(
        self, assigned: dict[str, list[Clip]], form: str, texts: dict[str, str],
        rejected: list[dict[str, Any]],
    ) -> str:  # fmt: skip
        """Fill `texts` with each clip's spoken text, move the clips without it from `assigned`
        to `rejected`, and return the languages wanted, for a message when none is left."""
        from avoc.stages.text_language import name_of
        from avoc.stages.text_subtitle import own_tag

        wanted: set[str] = set()
        for role, clips in assigned.items():
            # Whose name in the subtitles is this character's, from the clips exported for them.
            tag = own_tag(x for c in clips for x in c.spoken_hits or ())
            kept = []
            for clip in clips:
                language = self.workspace.spoken[clip.episode].language
                wanted.add(language)
                text, reason = self.text_of(clip, tag)
                if reason is None:
                    texts[clip.id] = text
                    kept.append(clip)
                else:
                    rejected.append({"role": role, "clip": clip, "reason": reason, "text": text})
            clips[:] = kept
        return say("、", ", ").join(name_of(code) for code in sorted(wanted))

    def export(self, roles: list[str], include_auto: bool, form: str, out: Path) -> dict[str, Any]:
        """Export the clips of these characters. For the formats with text, each clip's text is in
        the language spoken in its episode, and clips without it are left out and listed in
        rejected.tsv; see `spoken_of`."""
        from avoc.stages.export import export, summarize

        if form not in ("gpt-sovits", "folder"):
            raise ValueError(say("不认识的导出格式", "unknown export format"))
        if out.exists() and any(out.iterdir()):
            raise ValueError(
                say(
                    f"{out} 已存在且不是空的，换一个目录",
                    f"{out} already exists and is not empty. Pick another folder",
                )
            )
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
                rejected.append({"role": role, "clip": clip, "reason": str(UNUSABLE), "text": ""})
            else:
                assigned[role].append(clip)
        if not any(assigned.values()):
            raise ValueError(
                say(
                    f"没有可导出的片段：{len(rejected)} 条都标了质量低",
                    f"nothing to export: all {len(rejected)} clips are marked low quality",
                )
                if rejected
                else say("没有可导出的片段", "nothing to export")
            )
        texts: dict[str, str] = {}
        if form != "folder":
            problems = self._text_for_export(assigned, form, texts, rejected)
            if not any(assigned.values()):
                raise ValueError(
                    say(
                        f"一条也没导出：没有一条片段有{problems}台词。这些集是用别的语言的字幕切的，"
                        "只能导出音频；要文字就用这种语言的字幕重新加这几集",
                        f"nothing was exported: no clip has {problems} text. These episodes were "
                        "cut from subtitles in another language, so only audio can be exported; "
                        "for text, add them again with subtitles in that language",
                    )
                )
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
            language = self.workspace.spoken[item.episode].language
            if form == "gpt-sovits":
                lines.append(f"{item.path.resolve()}|{item.name}|{language}|{text}")
        if lines:
            (out / "train.list").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if rejected:
            _write_rejected(out / "rejected.tsv", rejected)
        reasons = Counter(r["reason"] for r in rejected)
        return {
            "out": str(out.resolve()),
            **summarize(written),
            "rejected": dict(reasons),
            "next": str(free_export_folder(self.workspace.root)),
        }


class LabelBody(BaseModel):
    clips: list[str]
    label: str | None = None
    """Character name, or "other". Empty means clear the label."""
    new_role: bool = False
    """Label as a newly made character that has no name yet. In that case `label` is not needed."""
    unusable: bool = False
    """Also mark as "low quality". Only works for target characters. When labeling as something
    else, or clearing the label, this is always turned off."""


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
    """JPEG or PNG, as a data URL."""


class ExportBody(BaseModel):
    roles: list[str]
    include_auto: bool = False
    form: str = "gpt-sovits"
    out: str


class AddBody(BaseModel):
    video: str = ""
    subtitles: str = ""
    display_subtitles: str = ""
    offset: float | None = None
    styles: list[str] | None = None
    """The subtitle styles that hold the dialogue. None picks them automatically."""
    spoken: str | None = None
    """The language spoken. None takes it from the video's audio track."""
    resume: str | None = None
    """Carry on with an episode that was not finished, using the files recorded for it."""


class ForgetBody(BaseModel):
    episode: str


class SubtitleStylesBody(BaseModel):
    path: str


class PickBody(BaseModel):
    kind: str
    """video, subtitles or folder"""
    current: str = ""
    """What the box holds now; the window opens in its folder."""


class PurposeBody(BaseModel):
    purpose: str


class SpokenBody(BaseModel):
    episode: str
    language: str


def free_export_folder(root: Path) -> Path:
    """Where an export goes unless the person picks another folder: exports/<today> in the
    workspace, or <today>-2 and so on when that one already holds an export."""
    base = root.resolve() / "exports" / time.strftime("%Y-%m-%d")
    folder, number = base, 1
    while folder.exists() and any(folder.iterdir()):
        number += 1
        folder = base.with_name(f"{base.name}-{number}")
    return folder


def _write_rejected(path: Path, rejected: list[dict[str, Any]]) -> None:
    """Clips whose text in the spoken language was not found in full, so they were not exported.
    One per line, so they can be found again in the interface."""
    rows = [
        say(
            "角色\t集\t开始\t结束\t原因\t主字幕\t找到的台词",
            "character\tepisode\tstart\tend\treason\tmain subtitles\ttext found",
        )
    ]
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
    # The process number keeps two apps open on the same project from writing into one file.
    temporary = target.with_suffix(f".{os.getpid()}.part.wav")
    sf.write(str(temporary), wave, rate, subtype="PCM_16")
    temporary.replace(target)


RELOAD_WORKSPACE = "AVOC_RELOAD_WORKSPACE"
RELOAD_MODELS = "AVOC_RELOAD_MODELS"


def reloaded_app() -> Any:
    """The app for `avoc app --reload`: uvicorn starts it afresh in a new process after each code
    change, with the workspace and models `avoc app` put in the environment."""
    models = tuple(m for m in os.environ.get(RELOAD_MODELS, "").split(",") if m)
    return create_app(AppState(Path(os.environ[RELOAD_WORKSPACE]), models or DEFAULT_MODELS))


def create_app(state: AppState) -> Any:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="avoc", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def always_check_page_files(request: Any, call_next: Any) -> Any:
        """Answer in the page's language (see avoc.language), and make the browser check the page,
        styles and script with the server every time (an unchanged file only gets a 304). Without
        that header the browser caches by modification time for a while, so a refresh after a UI
        change may still use the old styles or script."""
        LANGUAGE.set("en" if request.headers.get("x-language") == "en" else "zh")
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
            raise HTTPException(400, say("片段不存在", "no such clip"))
        with state.lock:
            label = state.store.new_role() if body.new_role else (body.label or "").strip() or None
            cast = {"unnamed": [label]} if body.new_role else None
            # One choice sets both "who it is" and "low quality". Labeling as clean turns off any
            # earlier "low quality" mark.
            changes: list[dict[str, Any]] = [{"clip": c, "label": label} for c in body.clips]
            role = state.store.role(label) if label else None
            # A new name creates a target character, so a name not yet in the character
            # list counts too.
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
        """A mixed batch of changes. It is recorded as one batch and undone as one batch. The
        Characters view's "confirm the rest" and "low quality" both go through here."""
        clean = []
        for change in body.changes:
            if change.get("clip") not in state.workspace.by_id:
                raise HTTPException(400, say("片段不存在", "no such clip"))
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
                raise HTTPException(400, say("不认识的改动", "unknown change"))
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
                return state.export(body.roles, body.include_auto, body.form, Path(body.out))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/purpose")
    def post_purpose(body: PurposeBody) -> dict[str, Any]:
        try:
            with state.lock:
                state.set_purpose(body.purpose)
                return state.summary()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/spoken-language")
    def post_spoken_language(body: SpokenBody) -> dict[str, Any]:
        try:
            with state.lock:
                state.set_spoken(body.episode, body.language)
                return state.summary()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/audio-tracks")
    def post_audio_tracks(body: SubtitleStylesBody) -> dict[str, Any]:
        """The audio tracks of a video, and the one `avoc add` would take with no language given,
        so the add form can show them."""
        from dataclasses import asdict

        from avoc.audio import audio_tracks, can_read
        from avoc.pipeline import choose_track
        from avoc.stages.text_language import from_tag

        path = clean_path(body.path)
        if not path.is_file():
            raise HTTPException(400, say(f"找不到视频：{path}", f"cannot find the video: {path}"))
        tracks = audio_tracks(path)
        if not tracks and not can_read(path):
            raise HTTPException(
                400,
                say(
                    "FFmpeg 读不了这个文件，它是视频吗",
                    "FFmpeg cannot read this file. Is it a video?",
                ),
            )
        if not tracks:
            return {"tracks": [], "number": None, "language": None, "from": None}
        number, language, how = choose_track(tracks, None)
        return {
            "tracks": [{**asdict(t), "language": from_tag(t.tag)} for t in tracks],
            "number": number,
            "language": language,
            "from": how,
        }

    @app.get("/api/doctor")
    def read_doctor() -> list[dict[str, Any]]:
        from dataclasses import asdict

        from avoc.doctor import checks

        return [asdict(c) for c in checks(state.workspace.root.resolve())]

    installing = threading.Lock()

    @app.post("/api/install-ffmpeg")
    def post_install_ffmpeg() -> dict[str, Any]:
        """Install FFmpeg with Scoop, and Scoop first when missing; takes a few minutes."""
        from avoc.doctor import install_ffmpeg

        if not installing.acquire(blocking=False):
            raise HTTPException(409, say("已经在装了", "already installing"))
        try:
            ok, output = install_ffmpeg()
        finally:
            installing.release()
        return {"ok": ok, "output": output}

    @app.get("/api/add")
    def read_adding() -> dict[str, Any]:
        return state.adding.status()

    @app.post("/api/add")
    def post_add(body: AddBody) -> dict[str, Any]:
        try:
            if body.resume:
                return state.adding.carry_on(body.resume)
            if not body.video.strip() or not body.subtitles.strip():
                raise ValueError(
                    say("视频和字幕都要填", "both the video and the subtitles are needed")
                )
            shown = clean_path(body.display_subtitles) if body.display_subtitles.strip() else None
            return state.adding.start(
                clean_path(body.video),
                clean_path(body.subtitles),
                body.offset,
                styles=body.styles,
                spoken=body.spoken or None,
                display_subtitles=shown,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/subtitle-styles")
    def post_subtitle_styles(body: SubtitleStylesBody) -> dict[str, Any]:
        """The styles in a subtitle file and the ones picked as dialogue, so the person can check
        and change them before adding the episode."""
        from avoc.stages.subtitle import describe_styles
        from avoc.stages.text_subtitle import subtitle_languages

        path = clean_path(body.path)
        try:
            if not path.is_file():
                raise ValueError(
                    say(f"找不到字幕文件：{path}", f"cannot find the subtitles: {path}")
                )
            found = describe_styles(path)
            languages = subtitle_languages(path, found["picked"] or None)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            **found,
            "marked": marked_note(found["marked"]) if found["marked"] else None,
            "languages": list(languages),
        }

    @app.post("/api/pick")
    def post_pick(body: PickBody) -> dict[str, Any]:
        """Open the system's file window on this machine and wait for the person (see picker)."""
        from avoc.app.picker import pick, start_folder

        try:
            return {"path": pick(body.kind, start_folder(body.current, Path.cwd()))}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/show-folder")
    def post_show_folder(body: SubtitleStylesBody) -> dict[str, Any]:
        """Open a folder, such as the export just written, in the file manager on this machine."""
        from avoc.app.picker import show_folder

        try:
            show_folder(clean_path(body.path))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {}

    @app.post("/api/add/stop")
    def post_add_stop() -> dict[str, Any]:
        return state.adding.stop()

    @app.post("/api/add/forget")
    def post_add_forget(body: ForgetBody) -> dict[str, Any]:
        try:
            state.adding.forget(body.episode)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return state.summary()

    # The avatar route must come before /media/{kind}/{clip_id}, or "avatar" would be
    # taken as a kind.
    @app.get("/media/avatar/{file}")
    def read_avatar(file: str) -> Any:
        path = state.workspace.labels_dir / "avatars" / file
        if not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png)", file) or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/media/{kind}/{clip_id}")
    def read_media(kind: str, clip_id: str, context: int = 0, fresh: int = 0) -> Any:
        clip_id = clip_id.rsplit(".", 1)[0]
        if kind not in ("audio", "video"):
            raise HTTPException(404)
        try:
            return FileResponse(state.media(kind, clip_id, context, fresh=bool(fresh)))
        except KeyError as exc:
            raise HTTPException(404) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/prefetch")
    def post_prefetch(body: PrefetchBody) -> dict[str, Any]:
        """The web page calls this when the person sees a line. In the background, clips from one
        minute before and after are cut first."""
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
