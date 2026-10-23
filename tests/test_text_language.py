from __future__ import annotations

from avoc.audio import AudioTrack
from avoc.pipeline import choose_track
from avoc.stages.text_language import (
    clear_language,
    file_languages,
    from_tag,
    line_languages,
    place_language,
)


def test_kana_and_hangul_decide_and_one_kana_is_not_enough() -> None:
    assert clear_language("ボクだよ") == "ja"
    assert clear_language("안녕하세요") == "ko"
    assert clear_language("我の天") is None  # Chinese sometimes borrows の.
    assert clear_language("押忍！") is None


def test_lines_without_kana_follow_their_place() -> None:
    japanese = ["ボクだよ", "いくよ", "押忍！", "６連勝", "はちみー"]
    assert place_language(japanese) == "ja"
    assert place_language(["我们走吧", "加油", "好的 OK"]) == "zh"
    assert place_language(["Let's go", "OK"]) == "en"
    assert place_language(["……", "123"]) is None


def test_bilingual_styles_are_told_apart() -> None:
    entries = [("CN", ["加油"]), ("JP", ["頑張って"]), ("CN", ["六连胜"]), ("JP", ["６連勝"])]
    assert line_languages(entries) == [["zh"], ["ja"], ["zh"], ["ja"]]
    assert file_languages(["zh", "ja", "zh", "ja", None]) == {"zh": 0.5, "ja": 0.5}
    assert file_languages(["ja"] * 9 + ["zh"]) == {"ja": 0.9}


def test_track_tags() -> None:
    assert from_tag("jpn") == from_tag("ja-JP") == "ja"
    assert from_tag("chi") == "zh" and from_tag("und") is None and from_tag("") is None


def test_the_japanese_track_is_chosen_over_a_default_dub() -> None:
    tracks = [AudioTrack(0, "eng", True), AudioTrack(1, "jpn", False), AudioTrack(2, "chi", False)]
    assert choose_track(tracks, None) == (1, "ja", "track")
    assert choose_track(tracks, "zh") == (2, "zh", "person")
    # A language no track is tagged with: the default track, as the person said.
    assert choose_track(tracks, "ko") == (0, "ko", "person")
    assert choose_track([AudioTrack(0, "", False)], None) == (0, "ja", "assumed")
    assert choose_track([AudioTrack(0, "eng", False)], None) == (0, "en", "track")
