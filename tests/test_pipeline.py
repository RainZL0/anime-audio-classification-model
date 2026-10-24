"""Regression tests.

Covers: the voiceprint cache, preparing and adding episodes, and the command list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from avoc import pipeline
from avoc.cli import app
from avoc.project import cache_signature, read_json, segment_rows, write_json


def episode(root: Path, name: str) -> Path:
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    sf.write(vocals, np.sin(np.arange(44100 * 6) * 0.05) * 0.1, 44100)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(b"fixture for cache fingerprint")
    write_json(
        directory / "episode.json",
        {
            "schema": "episode.v1",
            "name": name,
            "vocals": str(vocals),
            "analysis": str(analysis),
            "source": str(vocals),
            "sample_rate": 44100,
        },
    )
    rows = segment_rows(
        name, [{"start": 0, "end": 2}, {"start": 2, "end": 4}, {"start": 5, "end": 5.5}]
    )
    write_json(directory / "segments.json", rows)
    cache = directory / "embeddings/redimnet2-b6"
    cache.mkdir(parents=True)
    np.save(cache / "vectors.npy", np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32))
    write_json(cache / "metadata.json", rows[:2])
    write_json(cache / "cache.json", cache_signature(directory, "redimnet2-b6"))
    return directory


def test_cached_embed_does_not_load_models(tmp_path: Path, monkeypatch: Any) -> None:
    directory = episode(tmp_path, "ep1")

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Reusing the cache should not call the voiceprint model")

    monkeypatch.setattr(pipeline, "embed_segments", fail)
    assert pipeline.embed(directory)["cached"]


@pytest.mark.parametrize("changed", ["audio", "segments", "metadata"])
def test_cache_drift_is_detected(tmp_path: Path, changed: str) -> None:
    directory = episode(tmp_path, "ep1")
    if changed == "audio":
        (directory / "analysis.wav").write_bytes(b"changed")
    elif changed == "segments":
        write_json(directory / "segments.json", segment_rows("ep1", [{"start": 0, "end": 1.9}]))
    else:
        p = directory / "embeddings/redimnet2-b6/metadata.json"
        rows = read_json(p)
        rows[0]["end"] = 1.9
        write_json(p, rows)
    with pytest.raises(ValueError):
        pipeline.load_embeddings(directory, "redimnet2-b6")


def test_prepare_uses_subtitle_boundaries_keeps_short_lines(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from avoc import audio

    directory = episode(tmp_path, "ep1")
    source = directory / "ep1.wav"
    subtitles = tmp_path / "test.srt"
    subtitles.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHi\n\n2\n00:00:04,000 --> 00:00:04,500\nOh\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audio, "make_analysis_copy", lambda src, dst: dst.write_bytes(b"analysis"))

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("An explicit offset should not load the alignment model")

    monkeypatch.setattr(audio, "diarize", fail)
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "video_seconds", lambda path: audio.audio_info(source).duration)
    out = tmp_path / "prepared"
    pipeline.prepare(video, subtitles, out, "new", source, -0.5, audio=source)
    rows = read_json(out / "segments.json")
    assert [(r["start"], r["end"]) for r in rows] == [(0.5, 2.5), (3.5, 4.0)]
    assert not (out / "quality.json").exists()
    assert read_json(out / "episode.json")["video"] == str(video.resolve())


def test_prepare_cuts_subtitles_in_the_spoken_language_one_person_at_a_time(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from avoc import audio

    directory = episode(tmp_path, "ep1")
    source = directory / "ep1.wav"
    subtitles = tmp_path / "ja.srt"
    subtitles.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（マルゼン）ん？\n（記者）あれは\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nよかった\n思ったより元気そうね\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audio, "make_analysis_copy", lambda src, dst: dst.write_bytes(b"analysis"))
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "video_seconds", lambda path: audio.audio_info(source).duration)
    out = tmp_path / "prepared"
    result = pipeline.prepare(video, subtitles, out, "new", source, 0.0, audio=source, spoken="ja")
    rows = read_json(out / "segments.json")
    assert [(r["start"], round(r["end"], 3)) for r in rows] == [(1.0, 1.4), (1.4, 2.0), (3.0, 4.0)]
    assert result["by_turns"]
    assert read_json(out / "episode.json")["segmentation"] == "speaker_turns"


def test_prepare_refuses_audio_from_another_source(tmp_path: Path, monkeypatch: Any) -> None:
    directory = episode(tmp_path, "ep1")
    subtitles = tmp_path / "test.srt"
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "video_seconds", lambda path: 999.0)
    with pytest.raises(ValueError, match="different durations"):
        pipeline.prepare(video, subtitles, tmp_path / "x", "new", audio=directory / "ep1.wav")
    with pytest.raises(ValueError, match="Video does not exist"):
        pipeline.prepare(tmp_path / "none.mp4", subtitles, tmp_path / "y", "new")


def test_prepare_says_when_the_video_cannot_be_read(tmp_path: Path, monkeypatch: Any) -> None:
    import avoc.audio

    subtitles = tmp_path / "test.srt"
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    video = tmp_path / "ep1.mkv"
    video.write_bytes(b"not a video")
    monkeypatch.setattr(avoc.audio, "audio_tracks", lambda path: [])
    monkeypatch.setattr(avoc.audio, "can_read", lambda path: False)
    with pytest.raises(ValueError, match="Is it a video"):
        pipeline.prepare(video, subtitles, tmp_path / "x", "new", offset=0.0)
    monkeypatch.setattr(avoc.audio, "can_read", lambda path: True)
    with pytest.raises(ValueError, match="no audio track"):
        pipeline.prepare(video, subtitles, tmp_path / "x", "new", offset=0.0)
    assert not (tmp_path / "x").exists()


def test_add_refuses_a_missing_file_before_starting(tmp_path: Path) -> None:
    subtitles = tmp_path / "test.srt"
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"video")
    lines: list[str] = []
    with pytest.raises(ValueError, match="Display subtitles not found"):
        pipeline.add_episode(
            tmp_path / "ws", video, subtitles, display_subtitles=tmp_path / "none.ass",
            report=lines.append,
        )  # fmt: skip
    assert lines == []
    assert not (tmp_path / "ws").exists()


def test_prepare_without_offset_or_token_stops_before_writing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    subtitles = tmp_path / "test.srt"
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "has_hf_token", lambda: False)
    with pytest.raises(ValueError, match="--offset"):
        pipeline.prepare(video, subtitles, tmp_path / "out", "new")
    assert not (tmp_path / "out").exists()


def _fake_prepare(calls: list[str]) -> Any:
    def prepare(video: Path, subtitles: Path, out: Path, name: str, *args: Any) -> Any:
        calls.append(name)
        episode(out.parent, name)
        meta = read_json(out / "episode.json")
        write_json(out / "episode.json", {**meta, "video": str(video.resolve())})
        return {"episode": name, "segments": 3, "offset": -0.9, "overlap": None, "by_turns": False}

    return prepare


def test_add_names_the_next_episode_and_resumes_after_a_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    workspace = tmp_path / "ws"
    (workspace / "episodes" / "ep03").mkdir(parents=True)
    video, subtitles = tmp_path / "a.mp4", tmp_path / "a.srt"
    video.write_bytes(b"video")
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    prepared: list[str] = []
    monkeypatch.setattr(pipeline, "prepare", _fake_prepare(prepared))
    embedded: list[str] = []

    def embed_then_fail(directory: Path, model: str, device: str) -> Any:
        if model == "anime-char" and "anime-char" not in embedded:
            embedded.append(model)
            raise RuntimeError("not enough GPU memory")
        embedded.append(model)

    monkeypatch.setattr(pipeline, "embed", embed_then_fail)
    with pytest.raises(RuntimeError):
        pipeline.add_episode(workspace, video, subtitles, device="cpu")
    result = pipeline.add_episode(workspace, video, subtitles, device="cpu")
    assert result["episode"] == "ep04"
    assert prepared == ["ep04"]
    assert embedded == ["anime-va", "anime-char", "anime-va", "anime-char", "redimnet2-b6"]

    other = tmp_path / "b.mp4"
    other.write_bytes(b"video")
    with pytest.raises(ValueError, match="another video"):
        pipeline.add_episode(workspace, other, subtitles, name="ep04", device="cpu")


def test_text_subtitles_are_kept_for_a_run_that_carries_on(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A run stopped before the text subtitles were attached still attaches them when it carries
    on, even if --text-subs is not given again (as the interface's Carry on does)."""
    workspace = tmp_path / "ws"
    (workspace / "episodes").mkdir(parents=True)
    video, subtitles, japanese = tmp_path / "a.mp4", tmp_path / "a.srt", tmp_path / "a.ja.srt"
    video.write_bytes(b"video")
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    japanese.write_text("1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "prepare", _fake_prepare([]))
    attached: list[Path] = []
    monkeypatch.setattr(
        pipeline,
        "attach_text_subtitles",
        lambda out, path: attached.append(path) or {"text_subtitle_offset": 0.0, "matched": 1.0},
    )
    stopped = []

    def stop_once(directory: Path, model: str, device: str) -> None:
        if not stopped:
            stopped.append(model)
            raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "embed", stop_once)
    with pytest.raises(KeyboardInterrupt):
        pipeline.add_episode(workspace, video, subtitles, text_subtitles=japanese, device="cpu")
    pipeline.add_episode(workspace, video, subtitles, device="cpu")
    assert attached == [japanese.resolve()]
    meta = read_json(workspace / "episodes" / "ep01" / "episode.json")
    assert "pending_text_subtitles" not in meta


def test_add_removes_a_half_prepared_episode(tmp_path: Path, monkeypatch: Any) -> None:
    def broken(video: Path, subtitles: Path, out: Path, *args: Any) -> Any:
        out.mkdir(parents=True)
        (out / "source.flac").write_bytes(b"half")
        raise ValueError("Subtitle alignment overlap is too low")

    monkeypatch.setattr(pipeline, "prepare", broken)
    workspace = tmp_path / "ws"
    video, subtitles = tmp_path / "a.mp4", tmp_path / "a.srt"
    video.write_bytes(b"video")
    subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHi\n", encoding="utf-8")
    with pytest.raises(ValueError, match="overlap is too low"):
        pipeline.add_episode(workspace, video, subtitles, device="cpu")
    assert not (workspace / "episodes" / "ep01").exists()


def test_cli_has_one_route() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("doctor", "add", "prepare", "embed", "set-text-subtitles", "app"):
        assert command in result.stdout
    for old in ("group", "evaluate", "drift", "extend", "label-plan", "import-labels"):
        assert old not in result.stdout
