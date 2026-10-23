"""Human labels in a workspace: an append-only event log, plus a character list.

**Why append-only.** Each action is written as one line that records the state before and after
the change. Old lines are never edited. This way any step can be undone, and the full set of labels
at any moment can be replayed. If the power fails while writing, at most the last line is lost.

One line is one batch of changes (`batch`). Naming a whole group, or confirming the rest in one
click, is one batch, and undo takes back a whole batch at once.
An undo is also a batch. It records which batch it undid (`undo_of`), and a batch that was already
undone is never undone a second time.

**Target characters and "other".** The user only names the characters they want (target
characters). Everyone else is labeled "other" (`OTHER`).
"Other" means "not any target character at the time". So each "other" label also records which
target characters existed when it was made (`against`). If a new target character is added later,
old "other" labels do not count against it, and a person must check them again. When a target
character is removed, its labels stay as they are: a clip that belongs to one character is
certainly not any other target character, so it can still be used as a negative example. Adding
the character back loses nothing.

The blind labels (labels made without knowing the target characters) for episodes 1 to 3 are
archived in `annotations/`. Their labels were imported from there and migrated into target
characters and "other". The labels as they were before migration are archived next to them. See
`migrate_to_targets`.
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from avs.language import Words, say
from avs.project import read_json, write_json

PALETTE = (
    "#7F77DD",
    "#1D9E75",
    "#D85A30",
    "#D4537E",
    "#378ADD",
    "#639922",
    "#BA7517",
    "#E24B4A",
    "#5F5E5A",
    "#534AB7",
    "#0F6E56",
    "#993C1D",
    "#993556",
    "#185FA5",
    "#3B6D11",
    "#854F0B",
)
"""Colors are handed out in turn, in the order characters appear. A color only helps a person
recognize who is who. It means nothing more."""

UNNAMED = Words("角色 {}", "Character {}")
"""Characters the user has not named yet are called this for now. The name is only a key in the
label records, so naming a character is renaming it."""

OTHER = "__other__"
""""Other": not any target character at the time. Unsure clips, clips where several people talk
with no target character, and cheering sound effects are all labeled this."""

RETIRED = frozenset({"__unclear__", "__multiple__", "__not_speech__"})
"""Retired old labels: unsure, more than one person, or not speech. Since the question became only
"is it a target character?", these are no longer used. On 2026-10-23 they were all cleared, so
people re-listen under the new rules. When an old record is replayed, undone, or an old archive is
imported and these show up, they count as no label."""

FLAGS = ("unusable",)
"""Switches that can be turned on for a labeled target character. They are recorded separately
from the name, and the name still stands for the target.

`unusable` ("low quality"): too much background sound, someone else speaking at the same time, and
so on. Such clips cannot go into the clean dataset. They are not used to recognize people: they
are neither examples of the target nor negative examples, because the target's voice really is in
them. They are skipped on export.
Clips where several people talk and no target character is present are simply labeled "other".
They do not need this switch.
"""

OLD_FLAGS = {"overlap": "unusable"}
"""Switches that were renamed or merged. There used to be a separate "multiple people" switch,
later merged into "low quality". When old records are replayed, they count under the new name."""


def flag_of(change: dict[str, Any]) -> str | None:
    """Which switch this change sets, with old names swapped for new ones. Returns None if the
    change is not a switch change."""
    for key in (*FLAGS, *OLD_FLAGS):
        if key in change:
            return OLD_FLAGS.get(key, key)
    return None


def current(name: str | None) -> str | None:
    """Strip leading and trailing spaces. An empty label and a retired old label both count as no
    label."""
    name = (name or "").strip()
    return None if not name or name in RETIRED else name


class LabelStore:
    """Reads and writes one workspace's labels and character list. Every change goes through
    `apply`. It is thread-safe."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.events_path = folder / "events.jsonl"
        self.cast_path = folder / "cast.json"
        self.labels: dict[str, str] = {}
        self.against: dict[str, set[str]] = {}
        """Clips labeled "other", and which target characters existed when they were labeled."""
        self.rejects: dict[str, set[str]] = {}
        self.flags: dict[str, set[str]] = {flag: set() for flag in FLAGS}
        """Clips where each switch is on. See `FLAGS`."""
        self.unusable = self.flags["unusable"]
        self.batches: list[dict[str, Any]] = []
        self.roles: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        folder.mkdir(parents=True, exist_ok=True)
        if self.cast_path.exists():
            self.roles = list(read_json(self.cast_path)["roles"])
        # Early character lists did not have these fields. Back then every name was typed by a
        # person, so each one must be checked. Pattern numbers are filled in list order.
        for index, role in enumerate(self.roles):
            role.setdefault("named", True)
            role.setdefault("pattern", index)
            role.setdefault("target", True)
        if self.events_path.exists():
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    batch = json.loads(line)
                    self._replay(batch)
                    self.batches.append(batch)
        # The character list is the source of truth in cast.json. When replaying history, do not
        # create characters, or old names that were later renamed would come back.
        # Only names that still have clips but are missing from the list get added.
        missing = {n for n in self.labels.values() if n != OTHER and not self.role(n)}
        for name in sorted(missing):
            self._ensure_role(name, save=False)
        if missing:
            self._save_cast()

    # Reading

    def role(self, name: str) -> dict[str, Any] | None:
        return next((r for r in self.roles if r["name"] == name), None)

    def targets(self) -> list[str]:
        """The current target characters, in the order of the character list."""
        return [r["name"] for r in self.roles if r.get("target")]

    def can_undo(self) -> bool:
        return self._undoable() is not None

    # Writing

    def apply(
        self,
        changes: list[dict[str, Any]],
        source: str = "human",
        undo_of: int | None = None,
        cast: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Write one batch of changes. Each change is `{"clip", "label"}` (an empty `label` clears
        the label), `{"clip", "reject", "on"}` (this clip is not a certain character), or
        `{"clip", flag name: on or off}` (see `FLAGS`). Changes that do not actually change
        anything are dropped.

        When a clip is labeled "other", the current target characters are recorded. If the change
        includes `against`, that list is used instead (undo and migration do this).
        Characters this batch creates are recorded in the batch's `cast.created`. Renames and
        merges given in `cast` are recorded too. On undo, the character list is changed back. See
        `_undo_cast`."""
        with self._lock:
            targets = self.targets()
            effective: list[dict[str, Any]] = []
            created: list[str] = []
            for change in changes:
                clip = change["clip"]
                if "reject" in change:
                    before = change["reject"] in self.rejects.get(clip, set())
                    if before != bool(change["on"]):
                        effective.append(
                            {"clip": clip, "reject": change["reject"], "before": before,
                             "after": bool(change["on"])}
                        )  # fmt: skip
                    continue
                flag = flag_of(change)
                if flag is not None:
                    before = clip in self.flags[flag]
                    on = next(v for k, v in change.items() if OLD_FLAGS.get(k, k) == flag)
                    if before != bool(on):
                        effective.append(
                            {
                                "clip": clip,
                                flag: True,
                                "before": before,
                                "after": bool(on),
                            }
                        )
                    continue
                label = current(change.get("label"))
                previous = self.labels.get(clip)
                old = sorted(self.against.get(clip, ())) if previous == OTHER else None
                new = sorted(change.get("against", targets)) if label == OTHER else None
                if previous != label or old != new:
                    entry: dict[str, Any] = {"clip": clip, "before": previous, "after": label}
                    if old is not None:
                        entry["before_against"] = old
                    if new is not None:
                        entry["against"] = new
                    effective.append(entry)
                    if label is not None and label != OTHER:
                        if self.role(label) is None:
                            created.append(label)
                        self._ensure_role(label)
            # An undo is recorded even when nothing actually changes (for example, when it takes
            # back the batch that cleared retired old labels). Otherwise that batch would look
            # never undone, and repeated undo would get stuck on it.
            if not effective and undo_of is None:
                return None
            batch: dict[str, Any] = {
                "batch": (self.batches[-1]["batch"] + 1) if self.batches else 1,
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": source,
                "undo_of": undo_of,
                "changes": effective,
            }
            if created or cast:
                batch["cast"] = {**(cast or {}), **({"created": created} if created else {})}
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(batch, ensure_ascii=False) + "\n")
            self._replay(batch)
            self.batches.append(batch)
            return batch

    def undo(self) -> dict[str, Any] | None:
        """Take back the most recent manual batch that has not been undone yet."""
        with self._lock:
            target = self._undoable()
            if target is None:
                return None
            inverse = []
            for change in target["changes"]:
                if "reject" in change:
                    inverse.append(
                        {"clip": change["clip"], "reject": change["reject"], "on": change["before"]}
                    )
                elif (flag := flag_of(change)) is not None:
                    inverse.append({"clip": change["clip"], flag: change["before"]})
                else:
                    back: dict[str, Any] = {"clip": change["clip"], "label": change["before"]}
                    if "before_against" in change:
                        back["against"] = change["before_against"]
                    inverse.append(back)
            cast = target.get("cast", {})
            self._undo_cast(cast)
            batch = self.apply(inverse, source="undo", undo_of=target["batch"])
            # Characters this batch created are removed too once undo leaves them with no clips.
            # For example, making a new character with N and then undoing with Z leaves no empty
            # character behind.
            created = {*cast.get("created", ()), *cast.get("unnamed", ())}
            leftover = created - set(self.labels.values())
            if leftover:
                self.roles = [r for r in self.roles if r["name"] not in leftover]
                self._save_cast()
            return batch

    def update_role(self, name: str, **fields: Any) -> dict[str, Any]:
        """Change the color, the avatar, or whether this is a target character. To rename, use
        `rename_role`.

        Adding or removing target characters does not change any label. See the module notes."""
        with self._lock:
            role = self.role(name)
            if role is None:
                raise ValueError(say(f"没有这个角色：{name}", f"no such character: {name}"))
            for key in ("color", "avatar", "target"):
                if key in fields and fields[key] is not None:
                    role[key] = fields[key]
            self._save_cast()
            return role

    def new_role(self) -> str:
        """Make a character that has no name yet, and return its temporary name. Labels for it must
        be written next with `apply`, and `cast` must include `{"unnamed": [name]}`. Only then does
        undoing that batch remove this character too."""
        with self._lock:
            number = 1
            while self.role(str(UNNAMED).format(number)) is not None:
                number += 1
            name = str(UNNAMED).format(number)
            self._ensure_role(name, named=False)
            return name

    def rename_role(self, old: str, new: str) -> dict[str, Any] | None:
        """Rename, which is also how a name is given. If the new name already exists, this merges
        the two characters, so their clips are joined together."""
        new = new.strip()
        with self._lock:
            if self.role(old) is None:
                raise ValueError(say(f"没有这个角色：{old}", f"no such character: {old}"))
            if current(new) is None or new == OTHER:
                raise ValueError(
                    say(
                        "新名字不能为空，也不能是「其他」",
                        'the new name cannot be empty or "other"',
                    )
                )
            if new == old:
                return None
            moved: list[dict[str, Any]] = [
                {"clip": c, "label": new} for c, n in self.labels.items() if n == old
            ]
            cast: dict[str, Any]
            if self.role(new) is None:
                role = self.role(old)
                assert role is not None
                cast = {"renamed": {"from": old, "to": new, "named": role["named"]}}
                role["name"] = new
                role["named"] = True
            else:
                merged = self.role(old)
                kept = self.role(new)
                assert merged is not None and kept is not None
                cast = {
                    "merged": {
                        "role": dict(merged),
                        "at": self.roles.index(merged),
                        "into": new,
                        "target": bool(kept.get("target")),
                    }
                }
                kept["target"] = bool(kept.get("target")) or bool(merged.get("target"))
                self.roles = [r for r in self.roles if r["name"] != old]
            self._save_cast()
            for clip, names in self.rejects.items():
                if old in names:
                    moved.append({"clip": clip, "reject": old, "on": False})
                    moved.append({"clip": clip, "reject": new, "on": True})
            for clip, names in self.against.items():
                if old in names and self.labels.get(clip) == OTHER:
                    renamed = (names - {old}) | {new}
                    moved.append({"clip": clip, "label": OTHER, "against": sorted(renamed)})
            return self.apply(moved, cast=cast) if moved else None

    # Internal

    def _undo_cast(self, cast: dict[str, Any]) -> None:
        """When undoing a batch, first put back the renames and merges it made to the character
        list. Then put the labels back under their original names."""
        if renamed := cast.get("renamed"):
            role = self.role(renamed["to"])
            if role is not None and self.role(renamed["from"]) is None:
                role["name"] = renamed["from"]
                role["named"] = renamed["named"]
                self._save_cast()
        if merged := cast.get("merged"):
            kept = self.role(merged["into"])
            if kept is not None:
                kept["target"] = merged["target"]
            if self.role(merged["role"]["name"]) is None:
                self.roles.insert(min(merged["at"], len(self.roles)), dict(merged["role"]))
            self._save_cast()

    def _undoable(self) -> dict[str, Any] | None:
        undone = {b["undo_of"] for b in self.batches if b.get("undo_of") is not None}
        for batch in reversed(self.batches):
            if batch.get("undo_of") is None and batch["batch"] not in undone:
                if batch["source"].startswith("import"):
                    return None
                return batch
        return None

    def _replay(self, batch: dict[str, Any]) -> None:
        for change in batch["changes"]:
            clip = change["clip"]
            if "reject" in change:
                names = self.rejects.setdefault(clip, set())
                if change["after"]:
                    names.add(change["reject"])
                else:
                    names.discard(change["reject"])
            elif (flag := flag_of(change)) is not None:
                flagged = self.flags[flag]
                if change["after"]:
                    flagged.add(clip)
                else:
                    flagged.discard(clip)
            else:
                self.against.pop(clip, None)
                after = current(change["after"])
                if after is None:
                    self.labels.pop(clip, None)
                else:
                    self.labels[clip] = after
                    if after == OTHER:
                        self.against[clip] = set(change.get("against", ()))

    def _ensure_role(self, name: str, save: bool = True, named: bool = True) -> None:
        """A new character is a target character by default. A person who bothers to name someone
        probably wants that person."""
        if self.role(name) is None:
            # Pattern numbers only go up and are never reused. A character that was deleted or
            # merged does not pass its pattern on to a new character.
            pattern = max((int(r["pattern"]) for r in self.roles), default=-1) + 1
            self.roles.append(
                {
                    "name": name,
                    "named": named,
                    "color": PALETTE[pattern % len(PALETTE)],
                    "pattern": pattern,
                    "target": True,
                    "avatar": None,
                }
            )
            if save:
                self._save_cast()

    def _save_cast(self) -> None:
        write_json(self.cast_path, {"schema": "avs.cast.v1", "roles": self.roles})


def import_archives(
    store: LabelStore, archives: list[Path], by_time: dict[tuple[str, tuple[float, float]], str],
    sources: dict[str, str],
) -> int:  # fmt: skip
    """Import the names from the manual archives into the label records in one go. The whole
    import is recorded as one batch, and imported batches cannot be undone.

    `by_time` maps (episode name, time in milliseconds) to a clip ID. `sources` maps a vocals file
    name to an episode name.
    The imported names are first treated as target characters. Then `migrate_to_targets` turns
    them into target characters and "other".
    """
    from avs.project import time_key

    changes = []
    for path in archives:
        data = read_json(path)
        source = str(data["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"the audio of {path} is not in this workspace")
        episode = sources[source]
        for clip in data["clips"]:
            name = clip.get("name")
            clip_id = by_time.get((episode, time_key(clip)))
            if name and clip_id is not None:
                changes.append({"clip": clip_id, "label": name})
    batch = store.apply(changes, source="import:" + ",".join(p.name for p in archives))
    return len(batch["changes"]) if batch else 0


def migrate_to_targets(store: LabelStore, targets: list[str], archive: Path) -> int:
    """Keep only `targets` as target characters, and change the labels of every other character to
    "other". Returns how many labels changed.

    Before changing anything, copy the label records and the character list into `archive` as they
    are. The migration is recorded as one import batch, which undo cannot take back. To get the
    original names back, look at the archive, or at the event log's history from before this batch.
    """
    with store._lock:
        unknown = [t for t in targets if store.role(t) is None]
        if unknown:
            raise ValueError(f"no such characters: {', '.join(unknown)}")
        if archive.exists():
            raise ValueError(f"{archive} already exists; pick another archive folder")
        archive.mkdir(parents=True)
        for path in (store.events_path, store.cast_path):
            if path.exists():
                shutil.copy2(path, archive / path.name)
        for role in store.roles:
            role["target"] = role["name"] in targets
        store._save_cast()
        changes = [
            {"clip": clip, "label": OTHER, "against": sorted(targets)}
            for clip, name in store.labels.items()
            if name not in targets and name != OTHER
        ]
        batch = store.apply(changes, source="import:migrate-to-targets")
        return len(batch["changes"]) if batch else 0
