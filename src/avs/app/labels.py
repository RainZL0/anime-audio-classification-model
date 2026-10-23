"""工作区里的人工标签：只追加的事件记录，加一份角色表。

**为什么只追加。** 每次操作写成一行，记下改之前和改之后，旧的行永远不改。这样任何一步都能
撤销，也能回放出某个时刻的全部标签；文件写到一半断电，最多丢最后一行。

一行是一批改动（`batch`）：给一整组起名字、一键确认其余，都是一批，撤销时也整批撤回。
撤销本身也是一批，记下它撤的是哪一批（`undo_of`），被撤过的批次不会再被撤第二次。

**这里的标签跟 `annotations/` 下的人工归档分开放。** 修正界面会显示机器的预测，在这里标出来的
名字只拿来训练；打分用的检验集仍然按旧规矩整集盲标，见 docs/HISTORY.md 的「标注」。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from avs.labeling import SPECIAL
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
"""角色的颜色按出现顺序轮流取。颜色只帮人一眼认出是谁，不带别的意思。"""

UNNAMED = "角色 {}"
"""用户还没起名字的角色先叫这个。名字只是标签记录里的键，起名字就是改名。"""


def is_special(name: str | None) -> bool:
    return name is not None and name in SPECIAL


class LabelStore:
    """读写一个工作区的标签和角色表。所有改动都经过 `apply`，线程安全。"""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.events_path = folder / "events.jsonl"
        self.cast_path = folder / "cast.json"
        self.labels: dict[str, str] = {}
        self.rejects: dict[str, set[str]] = {}
        self.batches: list[dict[str, Any]] = []
        self.roles: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        folder.mkdir(parents=True, exist_ok=True)
        if self.cast_path.exists():
            self.roles = list(read_json(self.cast_path)["roles"])
        # 早期的角色表没有这两项：那时的名字都是人敲的；图案编号按表里的顺序补。
        for index, role in enumerate(self.roles):
            role.setdefault("named", True)
            role.setdefault("pattern", index)
        if self.events_path.exists():
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    batch = json.loads(line)
                    self._replay(batch)
                    self.batches.append(batch)
        # 角色表以 cast.json 为准；回放历史时不建角色，否则改过名的旧名字会复活。
        # 只给当前还有片段、却不在表里的名字补上。
        missing = {n for n in self.labels.values() if not is_special(n) and not self.role(n)}
        for name in sorted(missing):
            self._ensure_role(name, save=False)
        if missing:
            self._save_cast()

    # 读

    def role(self, name: str) -> dict[str, Any] | None:
        return next((r for r in self.roles if r["name"] == name), None)

    def trainable(self, name: str) -> bool:
        found = self.role(name)
        return found is not None and bool(found.get("trainable", True))

    def can_undo(self) -> bool:
        return self._undoable() is not None

    # 写

    def apply(
        self,
        changes: list[dict[str, Any]],
        source: str = "human",
        undo_of: int | None = None,
    ) -> dict[str, Any] | None:
        """写一批改动。每条改动是 `{"clip", "label"}`（`label` 为空表示清除），
        或 `{"clip", "reject", "on"}`（这条片段不是某个角色）。没有实际变化的改动会被丢掉。"""
        with self._lock:
            effective = []
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
                label = change.get("label") or None
                if label is not None:
                    label = label.strip()
                    if not label:
                        label = None
                previous = self.labels.get(clip)
                if previous != label:
                    effective.append({"clip": clip, "before": previous, "after": label})
                    if label is not None and not is_special(label):
                        self._ensure_role(label)
            if not effective:
                return None
            batch = {
                "batch": (self.batches[-1]["batch"] + 1) if self.batches else 1,
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": source,
                "undo_of": undo_of,
                "changes": effective,
            }
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(batch, ensure_ascii=False) + "\n")
            self._replay(batch)
            self.batches.append(batch)
            return batch

    def undo(self) -> dict[str, Any] | None:
        """撤回最近一批还没被撤过的人工改动。"""
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
                else:
                    inverse.append({"clip": change["clip"], "label": change["before"]})
            return self.apply(inverse, source="undo", undo_of=target["batch"])

    def update_role(self, name: str, **fields: Any) -> dict[str, Any]:
        """改颜色、头像、是否参与训练。改名走 `rename_role`。"""
        with self._lock:
            role = self.role(name)
            if role is None:
                raise ValueError(f"没有这个角色：{name}")
            for key in ("color", "avatar", "trainable"):
                if key in fields and fields[key] is not None:
                    role[key] = fields[key]
            self._save_cast()
            return role

    def new_role(self) -> str:
        """建一个还没起名字的角色，返回它的临时名字。"""
        with self._lock:
            number = 1
            while self.role(UNNAMED.format(number)) is not None:
                number += 1
            name = UNNAMED.format(number)
            self._ensure_role(name, named=False)
            return name

    def rename_role(self, old: str, new: str) -> dict[str, Any] | None:
        """改名，也就是起名字。新名字已经存在时就是合并，两个角色的片段归到一起。"""
        new = new.strip()
        with self._lock:
            if self.role(old) is None:
                raise ValueError(f"没有这个角色：{old}")
            if not new or is_special(new):
                raise ValueError("新名字不能为空，也不能是特殊标签")
            if new == old:
                return None
            moved: list[dict[str, Any]] = [
                {"clip": c, "label": new} for c, n in self.labels.items() if n == old
            ]
            if self.role(new) is None:
                role = self.role(old)
                assert role is not None
                role["name"] = new
                role["named"] = True
            else:
                self.roles = [r for r in self.roles if r["name"] != old]
            self._save_cast()
            for clip, names in self.rejects.items():
                if old in names:
                    moved.append({"clip": clip, "reject": old, "on": False})
            return self.apply(moved) if moved else None

    # 内部

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
            elif change["after"] is None:
                self.labels.pop(clip, None)
            else:
                self.labels[clip] = change["after"]

    def _ensure_role(self, name: str, save: bool = True, named: bool = True) -> None:
        if self.role(name) is None:
            # 图案编号只增不复用：删掉或合并掉的角色，它的图案不会落到新角色头上。
            pattern = max((int(r["pattern"]) for r in self.roles), default=-1) + 1
            self.roles.append(
                {
                    "name": name,
                    "named": named,
                    "color": PALETTE[pattern % len(PALETTE)],
                    "pattern": pattern,
                    "trainable": True,
                    "avatar": None,
                }
            )
            if save:
                self._save_cast()

    def _save_cast(self) -> None:
        write_json(self.cast_path, {"schema": "avs.cast.v1", "roles": self.roles})


def import_archives(
    store: LabelStore, archives: list[Path], by_time: dict[tuple[str, tuple[float, float]], str],
    sources: dict[str, str], untrained: list[str],
) -> int:  # fmt: skip
    """把人工归档里的名字一次性导进标签记录，整批记作一次导入，导入的批次不能撤销。

    `by_time` 是（集名, 毫秒时间）到片段 ID，`sources` 是人声文件名到集名。
    `untrained` 里的名字照样导进来，但标成不参与训练，比如「路人」这种一群人共用的名字。
    """
    from avs.project import time_key

    changes = []
    for path in archives:
        data = read_json(path)
        source = str(data["source"]).replace("\\", "/").rsplit("/", 1)[-1]
        if source not in sources:
            raise ValueError(f"{path} 的音轨不在这个工作区里")
        episode = sources[source]
        for clip in data["clips"]:
            name = clip.get("name")
            clip_id = by_time.get((episode, time_key(clip)))
            if name and clip_id is not None:
                changes.append({"clip": clip_id, "label": name})
    batch = store.apply(changes, source="import:" + ",".join(p.name for p in archives))
    for name in untrained:
        if store.role(name) is not None:
            store.update_role(name, trainable=False)
    return len(batch["changes"]) if batch else 0
