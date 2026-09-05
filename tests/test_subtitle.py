"""字幕自动对齐检查。"""

from avs.stages.subtitle import find_offset


def test_offset_is_measured_not_assumed() -> None:
    """字幕比音轨早 1 秒时，要量出 -1 秒这个偏移，把字幕挪回去。"""
    speech = [(10.0, 12.0), (20.0, 23.0), (30.0, 31.5)]
    lines = [(a + 1.0, b + 1.0) for a, b in speech]
    offset, overlap = find_offset(lines, speech, 40.0)
    assert abs(offset + 1.0) < 0.05
    assert overlap > 0.9


def test_offset_of_zero_when_already_aligned() -> None:
    """本来就对得上的时候不要乱挪。"""
    speech = [(5.0, 8.0), (15.0, 19.0)]
    offset, overlap = find_offset(speech, speech, 30.0)
    assert abs(offset) < 0.05
    assert overlap > 0.95


def test_wrong_subtitles_show_up_as_a_low_overlap() -> None:
    """拿错集数的字幕必须能从重合度上看出来，这是防安静错位的那道闸。"""
    speech = [(10.0, 12.0), (20.0, 23.0)]
    unrelated = [(40.0, 40.5), (60.0, 60.5)]
    _, overlap = find_offset(unrelated, speech, 90.0)
    assert overlap < 0.6
