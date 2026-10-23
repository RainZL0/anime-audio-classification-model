from __future__ import annotations

from pathlib import Path

import numpy as np
import pysubs2
import soundfile as sf
from fastapi.testclient import TestClient

from avs.app.server import AppState, create_app
from avs.project import read_json, write_json
from avs.stages.text_subtitle import TextLine, load_text_lines, match, measure_offset, own_tag
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


def test_offset_is_measured_against_the_cutting_subtitles() -> None:
    cut = [(1.0, 2.5), (4.0, 4.6), (7.2, 9.0)]
    lines = [TextLine(a + 2.0, b + 2.0, "x", "") for a, b in cut]
    offset, agreement = measure_offset(lines, cut)
    # The timeline is rounded to 10 ms, so the edges may differ by a step or two.
    assert offset == -2.0 and agreement > 0.99


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


def test_export_takes_text_from_the_attached_subtitles_and_reports_the_rest(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    state = AppState(root, ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    ids = [c.id for c in state.workspace.clips]
    client.post("/api/label", json={"clips": ids, "label": "A"})
    body = {"roles": ["A"], "form": "gpt-sovits", "language": "ja", "text_subtitles": True}

    early = client.post("/api/export", json={**body, "out": str(tmp_path / "early")})
    assert early.status_code == 400 and "还没配台词字幕" in early.json()["detail"]

    wrong = _srt(tmp_path / "wrong.srt", [(20.0 + k * 0.5, 20.2 + k * 0.5, "x") for k in range(6)])
    refused = client.post("/api/text-subtitles", json={"episode": "ep1", "path": str(wrong)})
    assert refused.status_code == 400 and "不是这一集" in refused.json()["detail"]

    ja = _srt(tmp_path / "ja.srt", [(a + 2.0, b + 2.0, t) for a, b, t in JA])
    summary = client.post("/api/text-subtitles", json={"episode": "ep1", "path": f'"{ja}"'}).json()
    attached = summary["episodes"][0]["text_subtitles"]
    assert attached["file"] == "ja.srt" and attached["offset"] == -2.0
    assert read_json(root / "episodes/ep1/episode.json")["text_subtitle_offset"] == -2.0

    out = tmp_path / "out"
    result = client.post("/api/export", json={**body, "out": str(out)}).json()
    assert result["files"] == 4
    assert result["rejected"] == {"台词里有别人的话": 1, "有一行台词只对上一部分": 1}
    texts = [
        line.rsplit("|", 1)[1] for line in (out / "train.list").read_text("utf-8").split("\n")[:-1]
    ]
    assert texts == ["ボクだよ", "いくよ", "はちみー", "よし がんばる"]
    report = (out / "rejected.tsv").read_text("utf-8").split("\n")
    assert report[0].startswith("角色\t集\t开始") and len(report) == 4
    assert "中文4" in report[1]

    plain = client.post(
        "/api/export", json={**body, "text_subtitles": False, "out": str(tmp_path / "plain")}
    )
    assert plain.json()["files"] == 6 and plain.json()["rejected"] == {}
