"""One workspace. Each episode has its own folder under `episodes/`. `labels/` holds the label
records and the character list.

On load, each clip's subtitle text is looked up from the subtitles, the clips are split into scenes
at pauses, and the caches of several voiceprint models are joined into one table. A clip shorter
than 0.5 seconds has no voiceprint (see MIN_SECONDS in embeddings/extract.py). These clips still
appear in the interface, but the machine cannot make a prediction for them, so a person must
identify them.

A clip shorter than `SKIP_SECONDS` that is also far from the lines before and after it is skipped
by default, so a person does not need to label it. See `Clip.skipped`.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avoc.language import Words
from avoc.pipeline import load_embeddings
from avoc.project import load_episode
from avoc.stages.text_subtitle import TextLine

SCENE_GAP = 3.0
"""If the pause between two lines of dialogue is longer than this many seconds, a new scene starts.
This is only used to split the dialogue for display. It does not affect identifying anyone."""

DEFAULT_MODELS = ("anime-va", "anime-char", "redimnet2-b6")
"""The three voiceprints work best together."""

GROUPING_MODEL = "anime-va"
"""The Groups view uses only this one model. Its threshold of 0.70 was measured. The joined
voiceprint was not measured."""

SKIP_SECONDS = 1.0
"""Clips shorter than this many seconds are of little use for training speech synthesis, so by
default a person does not need to label them."""

NEIGHBOR_GAP = 0.5
"""If a short clip is no more than this many seconds from the lines before and after it, the
subtitles may have split up one long line. It is still left for a person to label.

In episode 3, of the 36 named clips under 1 second, only 4 had a line from the same character
within 0.5 seconds."""


@dataclass(frozen=True)
class Clip:
    id: str
    episode: str
    start: float
    end: float
    text: str
    scene: int
    row: int | None
    """Row number in the voiceprint table. None when there is no voiceprint."""
    gap: float | None = None
    """How many seconds this clip is from the nearest other line (a different subtitle line or a
    different clip). It is 0 when touching or overlapping. It is None if this is the only line in
    the episode."""
    spoken_hits: tuple[TextLine, ...] | None = None
    """The lines in the spoken language that touch this clip (see `touching` in
    stages/text_subtitle.py). None when the episode has no text in the spoken language."""

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def skipped(self) -> bool:
        """Too short, with no line right next to it before or after. It is skipped by default, so a
        person does not need to label it."""
        return self.duration < SKIP_SECONDS and (self.gap is None or self.gap > NEIGHBOR_GAP)


@dataclass(frozen=True)
class SpokenText:
    """Where an episode's text in the spoken language comes from."""

    language: str
    assumed: bool
    """True when no tag or person said what is spoken, and Japanese was taken."""
    source: str | None
    """`text` (separate text subtitles), `cut` (the cutting subtitles are in that language), or
    None when there is no such text."""
    problem: Words | None = None
    """Why there is no text, for the person. None when there is."""
    lines: tuple[TextLine, ...] = ()
    """Lines in the spoken language, in audio-track time."""


def spoken_text(episode: dict[str, Any]) -> SpokenText:
    """Pick the source of the spoken-language text: separate text subtitles first, as the person
    chose them, then the cutting subtitles if they are in that language. A missing or unreadable
    file is reported, not raised, so the interface still opens."""
    from avoc.pipeline import spoken_language
    from avoc.stages.text_subtitle import load_text_lines, shifted, subtitle_languages, turn_lines

    spoken = spoken_language(episode)
    assumed = not episode.get("spoken_language") or episode.get("spoken_from") == "assumed"
    language = Words(name_of_in("zh", spoken), name_of_in("en", spoken))

    def failed(zh: str, en: str) -> SpokenText:
        return SpokenText(spoken, assumed, None, Words(zh, en))

    attached = episode.get("text_subtitles")
    if attached:
        path = Path(attached)
        if not path.is_file():
            return failed(f"配的台词字幕不见了：{path}", f"the text subtitles are missing: {path}")
        try:
            lines = load_text_lines(path, spoken=spoken)
        except ValueError as exc:
            return failed(str(exc), str(exc))
        if not lines:
            return failed(
                f"配的台词字幕里没有{language.zh}台词：{path.name}",
                f"the text subtitles have no {language.en} lines: {path.name}",
            )
        offset = float(episode.get("text_subtitle_offset") or 0.0)
        return SpokenText(spoken, assumed, "text", None, tuple(shifted(lines, offset)))
    path = Path(episode.get("subtitles") or "")
    if not path.is_file():
        return failed("没记切片段用的字幕", "no subtitles are recorded for cutting")
    styles = episode.get("subtitle_styles")
    offset = float(episode.get("subtitle_offset") or 0.0)
    try:
        if episode.get("segmentation") == "speaker_turns":
            # Cut one person at a time, so each clip's text is its own line; see `turn_lines`.
            lines = turn_lines(path, styles)
            return SpokenText(spoken, assumed, "cut", None, tuple(shifted(lines, offset)))
        if spoken in subtitle_languages(path, styles):
            lines = load_text_lines(path, styles, spoken)
            return SpokenText(spoken, assumed, "cut", None, tuple(shifted(lines, offset)))
    except ValueError as exc:
        return failed(str(exc), str(exc))
    return failed(
        f"没有{language.zh}字幕：切片段用的字幕不是{language.zh}，也没另配",
        f"no {language.en} subtitles: the cutting subtitles are not in {language.en}, and none "
        "are attached",
    )


def name_of_in(page: str, code: str) -> str:
    """A language's name in one page language, for messages built before a request."""
    from avoc.stages.text_language import LANGUAGES

    words = LANGUAGES.get(code)
    return (words.zh if page == "zh" else words.en) if words else code


def hits_for(lines: tuple[TextLine, ...], starts: list[float], reach: float, start: float,
             end: float) -> tuple[TextLine, ...]:  # fmt: skip
    """`touching` with a binary search: `starts` are the lines' starts and `reach` the longest
    line, so only lines that can reach the clip are looked at."""
    from avoc.stages.text_subtitle import touching

    low = bisect.bisect_left(starts, start - reach)
    high = bisect.bisect_right(starts, end)
    return tuple(touching(list(lines[low:high]), start, end))


@dataclass
class Workspace:
    root: Path
    episodes: dict[str, dict[str, Any]]
    """Episode name to the contents of episode.json, plus an extra `directory` entry."""
    clips: list[Clip]
    features: Any
    grouping: Any
    models: tuple[str, ...]
    skipped: dict[str, Words] = field(default_factory=dict)
    """Episode name to the reason it was not loaded. Usually the voiceprints are incomplete."""
    by_id: dict[str, Clip] = field(default_factory=dict)
    spoken: dict[str, SpokenText] = field(default_factory=dict)
    """Episode name to its text in the spoken language."""

    def __post_init__(self) -> None:
        self.by_id = {c.id: c for c in self.clips}

    @property
    def labels_dir(self) -> Path:
        return self.root / "labels"


def episode_dirs(root: Path) -> list[Path]:
    folder = root / "episodes"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if (p / "episode.json").exists())


MIN_TEXT_OVERLAP = 0.5
"""The overlap between a clip and a subtitle line must be at least this share of the shorter of the
two. Only then does the line count as the clip's dialogue.

Times are not matched exactly. In episodes 1 and 2, some clips were cut early by speech detection,
so their edges do not line up with subtitle lines."""


def subtitle_lines(episode: dict[str, Any]) -> list[tuple[float, float, str]]:
    """The subtitle lines for this episode, with the offset already added and converted to
    audio-track time. They come from the styles recorded when the episode was cut. Episodes cut
    before styles were recorded pick them again, which gives the same lines."""
    from avoc.stages.subtitle import load_dialogue
    from avoc.stages.text_subtitle import turn_lines

    path = Path(episode.get("subtitles") or "")
    if not path.is_file():
        return []
    offset = float(episode.get("subtitle_offset") or 0.0)
    styles = episode.get("subtitle_styles")
    if episode.get("segmentation") == "speaker_turns":
        return [(x.start + offset, x.end + offset, x.text) for x in turn_lines(path, styles)]
    lines = load_dialogue(path, styles)
    return [(line["start"] + offset, line["end"] + offset, line["text"]) for line in lines]


def display_lines(episode: dict[str, Any]) -> list[tuple[float, float, str]]:
    """The lines of the display subtitles (see `attach_display_subtitles` in pipeline.py), in
    audio-track time. Empty when there are none or the file is gone."""
    from avoc.stages.subtitle import load_dialogue

    path = Path(episode.get("display_subtitles") or "")
    if not path.is_file():
        return []
    offset = float(episode.get("display_subtitle_offset") or 0.0)
    lines = load_dialogue(path, episode.get("display_subtitle_styles"))
    return [(line["start"] + offset, line["end"] + offset, line["text"]) for line in lines]


def text_for(
    lines: list[tuple[float, float, str]], starts: list[float], start: float, end: float
) -> str:
    """The subtitle lines that overlap this time span enough. When a bilingual subtitle has
    several lines at the same time, they are joined with slashes."""
    found: list[str] = []
    at = bisect.bisect_left(starts, start - 20.0)
    for low, high, text in lines[at:]:
        if low >= end:
            break
        shared = min(high, end) - max(low, start)
        shorter = min(high - low, end - start)
        if shorter > 0 and shared >= MIN_TEXT_OVERLAP * shorter and text not in found:
            found.append(text)
    return " / ".join(found)


def neighbor_gap(
    spans: list[tuple[float, float]],
    at: int,
    lines: list[tuple[float, float, str]],
    line_starts: list[float],
) -> float | None:
    """`spans[at]` is how many seconds it is from the nearest other line. `spans` is all the clips
    in this episode, sorted by start time.

    The other line can be another clip, or a subtitle line that was not cut into a clip. This
    clip's own dialogue lines (the ones `text_for` counts as its lines) are not counted. If there
    is nothing within 20 seconds before or after, the result is None.
    """
    start, end = spans[at]
    span_starts = [s[0] for s in spans]
    low_at = bisect.bisect_left(span_starts, start - 20.0)
    high_at = bisect.bisect_left(span_starts, end + 20.0)
    others = [spans[k] for k in range(low_at, high_at) if k != at]
    for low, high, _ in lines[bisect.bisect_left(line_starts, start - 20.0) :]:
        if low >= end + 20.0:
            break
        shared = min(high, end) - max(low, start)
        shorter = min(high - low, end - start)
        if not (shorter > 0 and shared >= MIN_TEXT_OVERLAP * shorter):
            others.append((low, high))
    if not others:
        return None
    return max(min(max(low - end, start - high) for low, high in others), 0.0)


def load_workspace(
    root: Path, models: tuple[str, ...] = DEFAULT_MODELS, grouping: str = GROUPING_MODEL
) -> Workspace:
    import numpy as np

    episodes: dict[str, dict[str, Any]] = {}
    clips: list[Clip] = []
    feature_rows: list[Any] = []
    grouping_rows: list[Any] = []
    skipped: dict[str, Words] = {}
    spoken: dict[str, SpokenText] = {}
    for directory in episode_dirs(root):
        episode, rows = load_episode(directory)
        try:
            ids, parts = _aligned_vectors(directory, (*models, grouping))
        except (FileNotFoundError, ValueError) as exc:
            # Usually avoc add was interrupted partway. Skip this episode so the whole interface
            # does not fail to open.
            skipped[episode["name"]] = (
                Words(
                    "声纹没算全。在界面里点「接着做」，或者再运行一遍加这一集的 avoc add 命令",
                    "voiceprints are incomplete. Press Carry on in the interface, "
                    "or run the same avoc add command again",
                )
                if isinstance(exc, FileNotFoundError)
                else Words(
                    f"各声纹模型覆盖的片段不同，重跑 avoc embed（{exc}）",
                    f"the voiceprint models cover different clips; rerun avoc embed ({exc})",
                )
            )
            continue
        episodes[episode["name"]] = {**episode, "directory": str(directory)}
        joined = np.concatenate(parts[: len(models)], axis=1)
        joined /= np.linalg.norm(joined, axis=1, keepdims=True)
        position = {clip_id: len(feature_rows) + k for k, clip_id in enumerate(ids)}
        feature_rows.extend(joined)
        grouping_rows.extend(parts[-1])

        said = spoken[episode["name"]] = spoken_text(episode)
        said_starts = [x.start for x in said.lines]
        reach = max((x.end - x.start for x in said.lines), default=0.0)
        lines = subtitle_lines(episode)
        starts = [line[0] for line in lines]
        # With display subtitles, the line shown is theirs; the spoken text is shown under it.
        shown = display_lines(episode)
        shown_starts = [line[0] for line in shown]
        spans = sorted((float(row["start"]), float(row["end"])) for row in rows)
        gaps = {spans[k]: neighbor_gap(spans, k, lines, starts) for k in range(len(spans))}
        scene, previous_end = 0, None
        for row in rows:
            if previous_end is not None and row["start"] - previous_end > SCENE_GAP:
                scene += 1
            previous_end = row["end"] if previous_end is None else max(previous_end, row["end"])
            clips.append(
                Clip(
                    id=row["id"],
                    episode=episode["name"],
                    start=float(row["start"]),
                    end=float(row["end"]),
                    text=text_for(shown, shown_starts, float(row["start"]), float(row["end"]))
                    or text_for(lines, starts, float(row["start"]), float(row["end"])),
                    scene=scene,
                    row=position.get(row["id"]),
                    gap=gaps[(float(row["start"]), float(row["end"]))],
                    spoken_hits=None
                    if said.source is None
                    else hits_for(
                        said.lines, said_starts, reach, float(row["start"]), float(row["end"])
                    ),
                )
            )
    width = feature_rows[0].shape[0] if feature_rows else 0
    return Workspace(
        root=root,
        episodes=episodes,
        clips=clips,
        features=np.stack(feature_rows) if feature_rows else np.empty((0, width)),
        grouping=np.stack(grouping_rows) if grouping_rows else np.empty((0, 0)),
        models=models,
        skipped=skipped,
        spoken=spoken,
    )


def _aligned_vectors(directory: Path, models: tuple[str, ...]) -> tuple[list[str], list[Any]]:
    """Each model's voiceprints are put in the same clip order. If a cache is missing, this raises
    FileNotFoundError. If the models cover different clips, it raises ValueError."""
    parts = []
    ids: list[str] | None = None
    for model in models:
        records, vectors = load_embeddings(directory, model)
        order = {r["id"]: i for i, r in enumerate(records)}
        if ids is None:
            ids = [r["id"] for r in records]
        elif set(order) != set(ids):
            raise ValueError(str(directory))
        parts.append(vectors[[order[i] for i in ids]])
    assert ids is not None
    return ids, parts
