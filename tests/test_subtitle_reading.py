"""Reading subtitle files as they come: any common text encoding, and dialogue kept in styles with
any name."""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest
from typer.testing import CliRunner

from avoc.cli import app
from avoc.stages.subtitle import describe_styles, load_dialogue, pick_styles, read_subtitles

HEAD = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""  # noqa: E501
STYLE = "Style: {},Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1"  # noqa: E501


def clock(seconds: float) -> str:
    return f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{seconds % 60:05.2f}"


def ass(lines: list[tuple[str, float, float, str]]) -> str:
    """An ASS file with these (style, start, end, text) lines."""
    names = dict.fromkeys(style for style, *_ in lines)
    text = HEAD.format(styles="\n".join(STYLE.format(name) for name in names))
    for style, start, end, words in lines:
        text += f"Dialogue: 0,{clock(start)},{clock(end)},{style},,0,0,0,,{words}\n"
    return text


def spread(style: str, count: int, words: str = "line", until: float = 1400.0) -> list:
    """`count` lines spread evenly over an episode."""
    step = until / count
    return [(style, i * step, i * step + 2.0, f"{words} {i}") for i in range(count)]


def write(tmp_path: Path, text: str, encoding: str = "utf-8", name: str = "ep.ass") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


SRT_ZH = "".join(
    f"{i + 1}\n00:00:{i * 3:02d},000 --> 00:00:{i * 3 + 2:02d},000\n{line}\n\n"
    for i, line in enumerate(
        ["我们一定要赢下这场比赛", "帝王，你的腿还好吗？", "没问题的，我可是无敌的帝王大人！"] * 3
    )
)
SRT_TW = (
    SRT_ZH.replace("我们一定要赢下这场比赛", "我們一定要贏下這場比賽")
    .replace("你的腿还好吗", "你的腿還好嗎")
    .replace("没问题的，我可是无敌的帝王大人", "沒問題的，我可是無敵的帝王大人")
)
SRT_JA = "".join(
    f"{i + 1}\n00:00:{i * 3:02d},000 --> 00:00:{i * 3 + 2:02d},000\n{line}\n\n"
    for i, line in enumerate(
        [
            "絶対に勝ってみせるよ！",
            "テイオー、足は大丈夫なの？",
            "平気だって。ボクは無敵のテイオー様だもん！",
        ]
        * 3
    )
)


@pytest.mark.parametrize(
    ("text", "encoding"),
    [
        (SRT_ZH, "gb18030"),
        (SRT_ZH, "gbk"),
        (SRT_TW, "big5"),
        (SRT_JA, "cp932"),
        (SRT_JA, "utf-16"),  # Python writes a byte order mark first.
        (SRT_ZH, "utf-8-sig"),
    ],
)
def test_common_encodings_are_read(tmp_path: Path, text: str, encoding: str) -> None:
    path = write(tmp_path, text, encoding, "ep.srt")
    lines = load_dialogue(path)
    assert [line["text"] for line in lines] == [
        block.split("\n")[2] for block in text.strip().split("\n\n")
    ]


def test_broken_text_gives_a_reason_to_act_on(tmp_path: Path) -> None:
    """A file marked as UTF-8 that is not UTF-8 is not guessed at."""
    path = tmp_path / "ep.srt"
    path.write_bytes(codecs.BOM_UTF8 + SRT_ZH.encode("gb18030"))
    with pytest.raises(ValueError, match="Save it as UTF-8"):
        load_dialogue(path)


def test_a_file_that_is_not_subtitles_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read this subtitle file"):
        load_dialogue(write(tmp_path, "just some notes"))


def test_dialogue_is_found_whatever_the_style_is_called(tmp_path: Path) -> None:
    """The opening song has the most lines, but they all sit at the start, so it is not dialogue.
    Signs are spread out but few. A style named after the dialogue style is dialogue too."""
    lines = (
        spread("Dial", 300, "对白")
        + [("Dial - Top", 500.0 + i, 501.0 + i, "上方") for i in range(3)]
        + [("OP-kara", 30 + i * 0.3, 30.25 + i * 0.3, "歌") for i in range(400)]
        + spread("Sign", 30, "招牌")
    )
    path = write(tmp_path, ass(lines))
    assert pick_styles(read_subtitles(path)) == ["Dial", "Dial - Top"]
    texts = {line["text"].split()[0] for line in load_dialogue(path)}
    assert texts == {"对白", "上方"}


def test_bilingual_styles_are_both_dialogue(tmp_path: Path) -> None:
    path = write(tmp_path, ass(spread("CN", 300, "中文") + spread("JP", 290, "日本語")))
    assert pick_styles(read_subtitles(path)) == ["CN", "JP"]


def test_comments_and_drawings_are_not_dialogue(tmp_path: Path) -> None:
    text = ass(spread("Default", 20))
    text += "Comment: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,note\n"
    text += "Dialogue: 0,0:00:07.00,0:00:08.00,Default,,0,0,0,,{\\p1}m 0 0 l 100 0 100 100\n"
    lines = load_dialogue(write(tmp_path, text))
    assert len(lines) == 20
    assert all(line["text"].startswith("line") for line in lines)


def test_srt_lines_are_all_dialogue(tmp_path: Path) -> None:
    path = write(tmp_path, SRT_ZH, name="ep.srt")
    assert pick_styles(read_subtitles(path)) == ["Default"]
    assert len(load_dialogue(path)) == 9


def test_chosen_styles_win_and_wrong_names_are_refused(tmp_path: Path) -> None:
    path = write(tmp_path, ass(spread("Default", 50) + spread("Sign", 10, "招牌")))
    assert {line["text"].split()[0] for line in load_dialogue(path, ["Sign"])} == {"招牌"}
    with pytest.raises(ValueError, match=r"no style Dialogue\. Styles there: Default \(50\)"):
        load_dialogue(path, ["Dialogue"])
    with pytest.raises(ValueError, match="at least one style"):
        load_dialogue(path, [])


def test_styles_are_described_for_checking(tmp_path: Path) -> None:
    lines = spread("Default", 50, "我们一定要赢下这场比赛") + spread("Sign", 10, "招牌")
    found = describe_styles(write(tmp_path, ass(lines), "gb18030"))
    assert (found["format"], found["encoding"], found["picked"]) == ("ass", "gb18030", ["Default"])
    assert [(s["name"], s["lines"]) for s in found["styles"]] == [("Default", 50), ("Sign", 10)]
    assert found["styles"][1]["samples"] == ["招牌 0", "招牌 5", "招牌 9"]

    path = write(tmp_path, ass(lines), name="other.ass")
    result = CliRunner().invoke(app, ["styles", str(path)])
    assert result.exit_code == 0
    assert "* Default: 50 lines" in result.output
    assert "  Sign: 10 lines" in result.output


def test_the_interface_can_ask_for_the_styles(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from avoc.app.server import AppState, create_app

    path = write(tmp_path, ass(spread("Default", 50) + spread("Sign", 10, "招牌")))
    state = AppState(tmp_path / "work", ("redimnet2-b6",), grouping="redimnet2-b6")
    client = TestClient(create_app(state))
    found = client.post("/api/subtitle-styles", json={"path": f'"{path}"'}).json()
    assert found["picked"] == ["Default"]
    missing = client.post(
        "/api/subtitle-styles", json={"path": str(tmp_path / "x.ass")}, headers={"X-Language": "en"}
    )
    assert missing.status_code == 400
    assert "cannot find the subtitles" in missing.json()["detail"]
