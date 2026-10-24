from __future__ import annotations

from pathlib import Path

import numpy as np
import pysubs2
import soundfile as sf
from fastapi.testclient import TestClient

from avoc.app.server import AppState, create_app
from avoc.pipeline import attach_display_subtitles
from avoc.project import read_json, write_json
from avoc.stages.text_subtitle import (
    TextLine,
    load_text_lines,
    match,
    own_tag,
    subtitle_languages,
    turn_lines,
)
from tests.fixtures import episode


def _srt(path: Path, events: list[tuple[float, float, str]]) -> Path:
    subs = pysubs2.SSAFile()
    for start, end, text in events:
        subs.append(pysubs2.SSAEvent(start=int(start * 1000), end=int(end * 1000), text=text))
    subs.save(str(path))
    return path


def test_lines_are_split_by_speaker_and_lose_their_notes(tmp_path: Path) -> None:
    path = _srt(
        tmp_path / "ja.srt",
        [(1.0, 2.0, r"えへへ\N（マックイーン）まあ（ため息）"), (3.0, 4.0, "（歓声）")],
    )
    lines = load_text_lines(path)
    assert [(x.text, x.speaker) for x in lines] == [("えへへ", ""), ("まあ", "マックイーン")]
    # Times are split by character count: 3 characters against 2 characters
    assert lines[0].end == lines[1].start == 1.6


def test_a_line_shown_a_little_longer_than_spoken_still_counts() -> None:
    lines = [TextLine(0.5, 2.3, "ここは図書室", "")]
    assert match(lines, 1.0, 2.0) == ("ここは図書室", None)


def test_a_line_that_runs_well_past_the_clip_is_rejected() -> None:
    lines = [TextLine(0.0, 3.0, "えっ あ… でも 学校が…", "")]
    assert match(lines, 1.5, 2.5)[1] == "a line only partly matches"


def test_lines_of_someone_else_are_rejected_and_repeats_kept_once() -> None:
    lines = [
        TextLine(0.0, 0.6, "いや 全然", "テイオー"),
        TextLine(0.6, 1.4, "君のほうこそ", ""),
        TextLine(0.7, 1.4, "君のほうこそ", ""),
    ]
    assert match(lines, 0.0, 1.4, "テイオー") == ("いや 全然 君のほうこそ", None)
    mixed = [*lines, TextLine(1.0, 1.4, "えっ", "マックイーン")]
    assert match(mixed, 0.0, 1.4, "テイオー")[1] == "someone else's line is mixed in"
    # When the subtitles' name for her is not known, touching two different names also counts
    # as mixed.
    assert match(mixed, 0.0, 1.4)[1] == "someone else's line is mixed in"


def test_the_role_name_is_the_tag_most_of_her_lines_carry() -> None:
    def tagged(name: str) -> TextLine:
        return TextLine(0, 1, "x", name)

    assert own_tag([tagged("テイオー")] * 3 + [tagged("マックイーン"), tagged("")]) == "テイオー"
    assert own_tag([tagged("テイオー"), tagged("マックイーン")] * 2 + [tagged("")]) == "テイオー"
    assert own_tag([tagged("テイオー"), tagged("マックイーン"), tagged("スズカ")]) is None
    assert own_tag([tagged("")]) is None


JA = [
    (0.0, 0.9, "（テイオー）ボクだよ"),
    (1.0, 1.9, "（テイオー）いくよ"),
    (2.0, 2.9, "はちみー"),
    (3.0, 3.9, r"よし\Nがんばる"),
    (4.0, 4.9, r"えへへ\N（マックイーン）まあ"),
    (5.0, 6.9, "ずっと先まで続く長い台詞"),
    (7.3, 9.8, "片段にならなかった台詞"),
]


def _workspace(tmp_path: Path) -> Path:
    """One episode with 6 clips (clip i runs from i seconds to i + 0.9 seconds). The subtitles used
    for cutting match the clips one to one, with no offset.

    Clips exactly one second apart are too neat: a shift of exactly one second also fits well. So
    the subtitles end with one more line of a different length that was not cut into a clip.
    """
    root = tmp_path / "ws"
    (root / "episodes").mkdir(parents=True)
    directory = episode(root / "episodes", "ep1", np.eye(6)[:, :3] + 0.1)
    sf.write(directory / "ep1.wav", np.random.default_rng(0).normal(0, 0.05, 32000 * 10), 32000)
    cut = pysubs2.SSAFile()
    for i in range(6):
        cut.append(pysubs2.SSAEvent(start=i * 1000, end=i * 1000 + 900, text=f"中文{i}"))
    cut.append(pysubs2.SSAEvent(start=7300, end=9800, text="没切成片段的一行"))
    cut.save(str(directory / "cut.ass"))
    meta = read_json(directory / "episode.json")
    meta.update(subtitles=str(directory / "cut.ass"), subtitle_offset=0.0)
    write_json(directory / "episode.json", meta)
    return root


def _texts(listing: Path) -> list[str]:
    return [line.rsplit("|", 1)[1] for line in listing.read_text("utf-8").split("\n")[:-1]]


def test_an_episode_cut_from_a_translation_exports_sound_only(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    ids = [c.id for c in state.workspace.clips]
    client.post("/api/label", json={"clips": ids, "label": "A"})
    body = {"roles": ["A"], "form": "gpt-sovits"}

    # The main subtitles are Chinese, and the episode speaks Japanese (assumed: no tag).
    spoken = client.get("/api/state").json()["episodes"][0]["spoken"]
    assert spoken["language"] == "ja" and spoken["assumed"] and spoken["source"] is None
    assert spoken["blocked"] == 6
    clip = client.get("/api/clips").json()[0]
    assert clip["spoken"] == "" and "主字幕不是日语" in clip["spoken_problem"]
    refused = client.post("/api/export", json={**body, "out": str(tmp_path / "text")})
    assert refused.status_code == 400 and "没有一条片段有日语台词" in refused.json()["detail"]
    # Sound only needs no text.
    audio = client.post("/api/export", json={**body, "form": "folder", "out": str(tmp_path / "a")})
    assert audio.json()["files"] == 6

    # Saying the episode speaks Chinese makes the main subtitles its text.
    changed = client.post("/api/spoken-language", json={"episode": "ep1", "language": "zh"})
    spoken = changed.json()["episodes"][0]["spoken"]
    assert spoken["language"] == "zh" and not spoken["assumed"] and spoken["source"] == "cut"
    bad = client.post("/api/spoken-language", json={"episode": "ep1", "language": "fr"})
    assert bad.status_code == 400


def test_cutting_subtitles_in_the_spoken_language_give_the_text(tmp_path: Path) -> None:
    """Japanese cutting subtitles need nothing attached. An entry with two speakers is one clip
    with two people's voices, so it is left out."""
    root = _workspace(tmp_path)
    directory = root / "episodes/ep1"
    _srt(directory / "cut.ass", [(i, i + 0.9, t) for i, (_, _, t) in enumerate(JA[:6])])
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    client.post("/api/label", json={"clips": [c.id for c in state.workspace.clips], "label": "A"})
    assert client.get("/api/state").json()["episodes"][0]["spoken"]["source"] == "cut"
    out = tmp_path / "out"
    result = client.post("/api/export", json={"roles": ["A"], "out": str(out)}).json()
    assert result["rejected"] == {"台词里有别人的话": 1}
    assert _texts(out / "train.list")[:3] == ["ボクだよ", "いくよ", "はちみー"]


def test_cutting_lines_are_one_person_each_and_repeats_are_one_entry(tmp_path: Path) -> None:
    """One line broken into three entries in a row is one entry. Another entry shown at the same
    time stays its own. An entry with two named people is split by character count."""
    path = _srt(
        tmp_path / "ja.srt",
        [
            (0.0, 0.8, "わあ～！"),
            (0.8, 1.0, "わあ～！"),
            (1.0, 3.0, "わあ～！"),
            (1.0, 3.0, "ものすごい脚で"),
            (4.0, 5.0, r"（マルゼン）ん？\N（記者）あれは"),
            (6.0, 7.0, "わあ～！"),
        ],
    )
    lines = turn_lines(path)
    assert [(x.start, round(x.end, 6), x.text, x.speaker) for x in lines] == [
        (0.0, 3.0, "わあ～！", ""),
        (1.0, 3.0, "ものすごい脚で", ""),
        (4.0, 4.4, "ん？", "マルゼン"),
        (4.4, 5.0, "あれは", "記者"),
        (6.0, 7.0, "わあ～！", ""),
    ]


def test_the_main_line_is_shown_with_the_secondary_line_under_it(
    tmp_path: Path,
) -> None:
    """Cut from Japanese, one person at a time: each clip's own line is its text, with nothing to
    match. The Chinese secondary subtitles give the small line shown under it."""
    root = _workspace(tmp_path)
    directory = root / "episodes/ep1"
    lines = [(i, i + 0.9, t) for i, (_, _, t) in enumerate(JA[:4])] + [(7.3, 9.8, JA[6][2])]
    _srt(directory / "ja.srt", lines)
    meta = read_json(directory / "episode.json")
    write_json(
        directory / "episode.json",
        {**meta, "subtitles": str(directory / "ja.srt"), "segmentation": "speaker_turns"},
    )
    shown = attach_display_subtitles(directory, directory / "cut.ass")
    assert shown["display_subtitle_offset"] == 0.0
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    clips = TestClient(create_app(state)).get("/api/clips").json()
    assert [(c["text"], c["display"], c["spoken"]) for c in clips[:4]] == [
        ("ボクだよ", "中文0", "ボクだよ"),
        ("いくよ", "中文1", "いくよ"),
        ("はちみー", "中文2", "はちみー"),
        ("よし がんばる", "中文3", "よし がんばる"),
    ]
    assert all(c["spoken_problem"] is None for c in clips[:4])


def test_a_bilingual_file_keeps_only_the_spoken_lines(tmp_path: Path) -> None:
    """Chinese on the first line and Japanese on the second, as many fansubs do. The Japanese line
    gets the whole entry's time, and a kanji-only Japanese line still counts as Japanese."""
    entries = [(k, k + 0.9, rf"中文第{k}句\N日本語の台詞{k}だよ") for k in range(5)]
    entries.append((5.0, 5.9, r"六连胜\N６連勝"))
    path = _srt(tmp_path / "both.srt", entries)
    assert list(subtitle_languages(path)) == ["zh", "ja"]
    lines = load_text_lines(path, spoken="ja")
    assert [x.text for x in lines][-2:] == ["日本語の台詞4だよ", "６連勝"]
    assert lines[0].start == 0.0 and round(lines[0].end, 6) == 0.9
    assert [x.text for x in load_text_lines(path, spoken="zh")][-1] == "六连胜"
