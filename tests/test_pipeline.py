"""全量片段、缓存一致、身份真值精确匹配、原采样率导出的回归测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from avs import pipeline
from avs.cli import app
from avs.evaluation.identity import evaluate, identity_metrics
from avs.labeling import apply_names, build_sample
from avs.project import cache_signature, read_json, segment_rows, write_json


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
            "schema": "avs.episode.v1",
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


def test_group_export_includes_every_clip_and_small_groups(tmp_path: Path) -> None:
    episodes = [episode(tmp_path, name) for name in ("ep1", "ep2")]
    out = tmp_path / "groups.json"
    result = pipeline.group(episodes, out, model="redimnet2-b6")
    assert result["summary"] == {"clips": 6, "groups": 2, "singleton_groups": 0, "unassigned": 2}
    exported = pipeline.export_groups(out, tmp_path / "export")
    assert exported["files"] == 6
    assert len(list((tmp_path / "export/_unassigned").glob("*.wav"))) == 2
    assert all(sf.info(p).samplerate == 44100 for p in (tmp_path / "export").rglob("*.wav"))
    with pytest.raises(ValueError, match="已存在"):
        pipeline.export_groups(out, tmp_path / "export")


def test_grouping_and_cached_embed_do_not_load_models(tmp_path: Path, monkeypatch: Any) -> None:
    directory = episode(tmp_path, "ep1")

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("缓存复用不应调用声纹模型")

    monkeypatch.setattr(pipeline, "embed_segments", fail)
    assert pipeline.embed(directory)["cached"]
    a = pipeline.group([directory], tmp_path / "a.json", threshold=0.1, model="redimnet2-b6")
    b = pipeline.group([directory], tmp_path / "b.json", threshold=1.5, model="redimnet2-b6")
    assert a["summary"]["groups"] == 2
    assert b["summary"]["groups"] == 1


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
        pipeline.group([directory], tmp_path / "groups.json", model="redimnet2-b6")


def test_exact_annotations_and_unassigned_are_not_hidden(tmp_path: Path) -> None:
    directory = episode(tmp_path, "ep1")
    groups = tmp_path / "groups.json"
    pipeline.group([directory], groups, model="redimnet2-b6")
    archive = tmp_path / "truth.json"
    write_json(
        archive,
        {
            "source": "old/ep1.wav",
            "clips": [
                {"start": 0, "end": 2, "name": "A"},
                {"start": 5, "end": 5.5, "name": "A"},
                {"start": 0, "end": 4, "name": "B"},
            ],
        },
    )
    report = evaluate(groups, [archive])
    assert report["unmatched_labels"] == 1
    assert report["labeled_unassigned"] == 1
    assert report["metrics"]["labeled_clips"] == 2
    assert report["metrics"]["pair_recall"] == 0
    assert report["metrics"]["pair_precision"] is None
    assert evaluate(groups, [archive, archive])["metrics"]["labeled_clips"] == 2
    write_json(archive, {"source": "wrong.wav", "clips": []})
    with pytest.raises(ValueError, match="音轨"):
        evaluate(groups, [archive])


def test_identity_metric_does_not_reward_singletons_as_perfect() -> None:
    assert identity_metrics(["A", "A"], [0, 1])["pair_precision"] is None
    result = identity_metrics(["A", "A", "B"], [0, 1, 0])
    assert result["false_merged_pairs"] == 1
    assert result["missed_same_person_pairs"] == 1


def test_label_sample_uses_all_clips_and_preserves_archive(tmp_path: Path) -> None:
    directory = episode(tmp_path, "ep1")
    archive = tmp_path / "annotations.json"
    data = build_sample(directory, archive, 99)
    assert len(data["clips"]) == 3
    names = {data["clips"][0]["clip_id"]: "角色 A"}
    write_json(archive, apply_names(data, names))
    assert build_sample(directory, archive, 1)["clips"][0]["name"] == "角色 A"
    with pytest.raises(ValueError):
        apply_names(data, {"not-a-clip": "A"})


def test_prepare_uses_subtitle_boundaries_keeps_short_lines(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from avs import audio

    directory = episode(tmp_path, "ep1")
    source = directory / "ep1.wav"
    subtitles = tmp_path / "test.srt"
    subtitles.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHi\n\n2\n00:00:04,000 --> 00:00:04,500\nOh\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audio, "make_analysis_copy", lambda src, dst: dst.write_bytes(b"analysis"))

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("显式偏移不应加载对齐模型")

    monkeypatch.setattr(audio, "diarize", fail)
    out = tmp_path / "prepared"
    pipeline.prepare(source, subtitles, out, "new", source, -0.5)
    rows = read_json(out / "segments.json")
    assert [(r["start"], r["end"]) for r in rows] == [(0.5, 2.5), (3.5, 4.0)]
    assert not (out / "quality.json").exists()


def test_cli_has_one_route() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("prepare", "embed", "group", "evaluate", "export", "label"):
        assert command in result.stdout
    for old in ("probe", "propose", "audit", "multi"):
        assert old not in result.stdout
