"""Labels borrowed from another workspace, so the machine can guess from the first line.

When a show is cut again (say from Japanese subtitles in place of Chinese ones), the clips are
new, so the old labels do not fit them. But the voices are the same. So the new workspace can
borrow the old one's labels: on every retrain, the old workspace's labeled clips are added to the
examples, with their voiceprints from the same models. They only teach the machine; they are never
shown, guessed or exported. Once enough of the new workspace is labeled, stop borrowing and the old
labels drop out in one go. Nothing in either workspace's labels changes.

A borrowed label counts for a target character of this workspace with the same name, by the same
rules as this workspace's own labels (see `retrain` in server.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avoc.language import say
from avoc.project import read_json, write_json

FILE = "borrowed.json"
"""In the workspace's labels/ folder: `{"from": "<other workspace folder>"}`."""


@dataclass(frozen=True)
class Borrowed:
    root: Path
    features: Any
    """One row per labeled clip of the other workspace that has voiceprints, as in `Workspace`."""
    labels: list[str]
    against: list[set[str]]
    rejects: list[set[str]]


def borrowed_from(labels_dir: Path) -> Path | None:
    path = labels_dir / FILE
    return Path(read_json(path)["from"]) if path.exists() else None


def start(root: Path, other: Path) -> list[str]:
    """Borrow `other`'s labels for the workspace at `root`. Its target characters missing here are
    added as targets, with their color and avatar, so their names match. Returns those names."""
    from avoc.app.labels import LabelStore

    other = other.resolve()
    if other == root.resolve():
        raise ValueError(say("不能借自己的标注", "a workspace cannot borrow its own labels"))
    if not (other / "labels" / "events.jsonl").exists():
        raise ValueError(say(f"{other} 里没有标注", f"{other} has no labels"))
    theirs = LabelStore(other / "labels")
    ours = LabelStore(root / "labels")
    added = []
    for role in theirs.roles:
        if role.get("target") and ours.role(role["name"]) is None:
            avatar = role.get("avatar")
            if avatar and (other / "labels" / "avatars" / avatar).is_file():
                folder = root / "labels" / "avatars"
                folder.mkdir(exist_ok=True)
                (folder / avatar).write_bytes((other / "labels" / "avatars" / avatar).read_bytes())
            else:
                avatar = None
            ours._ensure_role(role["name"])
            ours.update_role(role["name"], color=role["color"], avatar=avatar)
            added.append(role["name"])
    write_json(root / "labels" / FILE, {"from": str(other)})
    return added


def stop(root: Path) -> bool:
    """Stop borrowing. Returns False when nothing was borrowed."""
    path = root / "labels" / FILE
    if not path.exists():
        return False
    path.unlink()
    return True


def load(other: Path, models: tuple[str, ...]) -> Borrowed:
    """The other workspace's labeled clips with their voiceprints. Clips marked "low quality" and
    episodes without all the voiceprints are left out."""
    import numpy as np

    from avoc.app.labels import LabelStore
    from avoc.app.workspace import _aligned_vectors, episode_dirs

    store = LabelStore(other / "labels")
    wanted = {c for c in (*store.labels, *store.rejects) if c not in store.unusable}
    rows: list[Any] = []
    labels: list[str] = []
    against: list[set[str]] = []
    rejects: list[set[str]] = []
    for directory in episode_dirs(other):
        try:
            ids, parts = _aligned_vectors(directory, models)
        except (FileNotFoundError, ValueError):
            continue
        joined = np.concatenate(parts, axis=1)
        joined /= np.linalg.norm(joined, axis=1, keepdims=True)
        for k, clip in enumerate(ids):
            if clip in wanted:
                rows.append(joined[k])
                labels.append(store.labels.get(clip, ""))
                against.append(store.against.get(clip, set()))
                rejects.append(store.rejects.get(clip, set()))
    return Borrowed(
        root=other,
        features=np.stack(rows) if rows else np.empty((0, 0)),
        labels=labels,
        against=against,
        rejects=rejects,
    )
