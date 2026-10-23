"""Caption habits found in real subtitles: each case is a line seen in Netflix, Amazon or Japanese
TV captions, or a common habit of English subtitles for viewers who cannot hear."""

from __future__ import annotations

import pytest

from avoc.stages.captions import marked, spoken, spoken_lines
from avoc.stages.text_subtitle import same_name


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        # Speaker names: in brackets, wrapped over two lines, alone on the line above, with a colon.
        ("（テイオー）ねえ カイチョー！", [("ねえ カイチョー！", "テイオー")]),
        (
            "（サトノダイヤモンド・\nキタサンブラック）おお…",
            [("おお…", "サトノダイヤモンド・キタサンブラック")],
        ),
        ("（女性）\nあっ それじゃあ", [("あっ それじゃあ", "女性")]),
        ("《リオナタール：何か", [("何か", "リオナタール")]),
        ("２人：コイツには 絶対 負けない", [("コイツには 絶対 負けない", "２人")]),
        ("JOHN: Wait!", [("Wait!", "JOHN")]),
        ("Note: this is dialogue", [("Note: this is dialogue", "")]),
        ("It starts at 10:30", [("It starts at 10:30", "")]),
        # A reading inside a name, and a sign before it.
        ("（細江純子(じゅんこ)）お願いいたします", [("お願いいたします", "細江純子")]),
        ("📱（サイレンススズカ）リハビリで", [("リハビリで", "サイレンススズカ")]),
        # Sound notes, alone or wrapped, and signs in square brackets.
        ("（歓声）", []),
        ("（マヤノトップガンの\n寝息）", []),
        ("ごめんね（笑い声）スズカ", [("ごめんねスズカ", "")]),
        ("Hello (laughs) there", [("Hello there", "")]),
        ("[[]]そして　楽しみなレースは続きます。", [("そして 楽しみなレースは続きます。", "")]),
        ("[ﾏｲｸ]まさか　まさかの　２着！", [("まさか まさかの ２着！", "")]),
        ("[laughs] Okay.", [("Okay.", "")]),
        # Song lyrics, and a note that only decorates a line.
        ("♪ 光の速さで", []),
        ("～♪", []),
        ("♬「必要と言うのなら」", []),
        ("やった～♪", [("やった～", "")]),
        # Marks around spoken words, and TV caption signs.
        (
            "《あれだけ　トレーニングしたんだ。\nいける！》",
            [("あれだけ トレーニングしたんだ。", ""), ("いける！", "")],
        ),
        ("((ゲェー！))", [("ゲェー！", "")]),
        ("更に才能が開花しましたし➡", [("更に才能が開花しましたし", "")]),
        ("micさぁ", [("さぁ", "")]),
        ("🎤第２コーナーを回りまして", [("第２コーナーを回りまして", "")]),
        # Readings, half-width katakana, dashes.
        ("暮れの中山(なかやま)レース場", [("暮れの中山レース場", "")]),
        ("今 トゥインクル･シリーズで", [("今 トゥインクル・シリーズで", "")]),
        ("- Hey.\n- What?", [("Hey.", ""), ("What?", "")]),
    ],
)
def test_caption_habits(entry: str, expected: list[tuple[str, str]]) -> None:
    assert spoken_lines(entry) == expected


def test_line_breaks_from_srt_files_are_ignored() -> None:
    assert (
        spoken("（スズカ）よかった\r\n思ったより元気そうね\r\n\r")
        == "よかった 思ったより元気そうね"
    )


def test_unknown_marks_are_reported() -> None:
    assert marked(["ふつうの台詞", "ふつうの台詞"]) is None
    found = marked(["〈ナレーター〉昔々", "「ok」", "【回想", "【回想"])
    assert found == {"lines": 2, "examples": ["〈ナレーター〉昔々", "【回想"]}


def test_full_and_short_names_are_the_same_person() -> None:
    assert same_name("トウカイテイオー", "テイオー")
    assert same_name("テイオー", "トウカイテイオー")
    assert not same_name("テイオーたち", "テイオー")
