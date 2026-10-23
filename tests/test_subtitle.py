"""Automatic subtitle alignment check."""

from avoc.stages.subtitle import find_offset


def test_offset_is_measured_not_assumed() -> None:
    """When the subtitles are 1 second early compared with the audio track,
    measure the -1 second offset and shift the subtitles back."""
    speech = [(10.0, 12.0), (20.0, 23.0), (30.0, 31.5)]
    lines = [(a + 1.0, b + 1.0) for a, b in speech]
    offset, overlap = find_offset(lines, speech, 40.0)
    assert abs(offset + 1.0) < 0.05
    assert overlap > 0.9


def test_offset_of_zero_when_already_aligned() -> None:
    """When the subtitles already line up, do not shift them."""
    speech = [(5.0, 8.0), (15.0, 19.0)]
    offset, overlap = find_offset(speech, speech, 30.0)
    assert abs(offset) < 0.05
    assert overlap > 0.95


def test_wrong_subtitles_show_up_as_a_low_overlap() -> None:
    """Subtitles from the wrong episode must show up as a low overlap.
    This is the check that guards against silent misalignment."""
    speech = [(10.0, 12.0), (20.0, 23.0)]
    unrelated = [(40.0, 40.5), (60.0, 60.5)]
    _, overlap = find_offset(unrelated, speech, 90.0)
    assert overlap < 0.6
