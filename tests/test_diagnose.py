"""嵌入诊断：排除自身、单标签角色只当干扰项、未标注近邻只算线索、两模型同池。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from avs.evaluation.diagnose import diagnose, duration_bin
from avs.project import cache_signature, digest, read_json, segment_rows, write_json

MODELS = ["redimnet2-b6", "wespeaker-resnet293"]


def _unit(rows: list[list[float]]) -> np.ndarray:
    matrix = np.array(rows, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def _episode(
    root: Path, name: str, spans: list[tuple[float, float]], vectors: dict[str, np.ndarray]
) -> Path:
    directory = root / name
    directory.mkdir()
    vocals = directory / f"{name}.wav"
    sf.write(vocals, np.sin(np.arange(44100 * 8) * 0.05) * 0.1, 44100)
    analysis = directory / "analysis.wav"
    analysis.write_bytes(name.encode())
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
    rows = segment_rows(name, [{"start": a, "end": b} for a, b in spans])
    write_json(directory / "segments.json", rows)
    for model, matrix in vectors.items():
        cache = directory / "embeddings" / model
        cache.mkdir(parents=True)
        # 第二个模型倒序保存，检验按片段 ID 对齐而不是按行号。
        order = slice(None) if model == MODELS[0] else slice(None, None, -1)
        np.save(cache / "vectors.npy", matrix[order])
        write_json(cache / "metadata.json", rows[order])
        write_json(cache / "cache.json", cache_signature(directory, model))
    return directory


def _fixture(tmp_path: Path) -> tuple[list[Path], Path]:
    # ep1：A、A、A；ep2：B、B、未标注。第二个模型把 A 的第三条推向 B。
    ep1 = _episode(
        tmp_path,
        "ep1",
        [(0, 2), (2, 4), (4, 5.2)],
        {
            MODELS[0]: _unit([[1, 0, 0], [1, 0, 0], [0.6, 0, 0.8]]),
            MODELS[1]: _unit([[1, 0, 0], [1, 0, 0], [0, 0.6, 0.8]]),
        },
    )
    ep2 = _episode(
        tmp_path,
        "ep2",
        [(0, 1), (1, 2.5), (3, 5)],
        {
            MODELS[0]: _unit([[0, 1, 0], [0, 1, 0], [0, 0, 1]]),
            MODELS[1]: _unit([[0, 1, 0], [0, 1, 0], [0, 0, 1]]),
        },
    )
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {
            "source": "ep1.wav",
            "clips": [
                {"start": 0, "end": 2, "name": "A"},
                {"start": 2, "end": 4, "name": "A"},
                {"start": 4, "end": 5.2, "name": "A"},
                {"start": 6, "end": 7, "name": "__multiple__"},
            ],
        },
    )
    second = tmp_path / "truth2.json"
    write_json(
        second,
        {
            "source": "ep2.wav",
            "clips": [{"start": 0, "end": 1, "name": "B"}, {"start": 1, "end": 2.5, "name": "B"}],
        },
    )
    return [ep1, ep2], annotation


def test_retrieval_excludes_self_and_reports_unlabeled_neighbours_as_leads(tmp_path: Path) -> None:
    episodes, annotation = _fixture(tmp_path)
    out = tmp_path / "diagnosis"
    report = diagnose(episodes, [annotation, tmp_path / "truth2.json"], MODELS, out)
    assert report["pool"] == {
        "embedded_clips": 6,
        "labeled_clips": 5,
        "unmatched_labels": 0,
        "special_labels": 1,
        "roles": 2,
        "query_roles": 2,
        "single_label_roles": [],
    }
    first, second = (report["models"][m]["retrieval"] for m in MODELS)
    assert first["queries"] == second["queries"] == 5
    assert first["top1_hit_rate"] == 1.0
    assert second["top1_hit_rate"] == 0.8
    assert second["top3_hit_rate"] == 1.0
    assert first["same_episode"] == {"evaluable": 5, "top1_hit_rate": 1.0}
    assert first["cross_episode"] == {"evaluable": 0, "top1_hit_rate": None}
    # A 的第三条在全池里最近的是 ep2 那条未标注片段，只能记为线索。
    assert first["full_pool_top1"] == {"same_role": 4, "unlabeled": 1}
    assert first["by_duration"]["0-1.5s"] == {"queries": 2, "top1_hit_rate": 1.0}
    third = next(q for q in report["models"][MODELS[0]]["queries"] if q["start"] == 4)
    assert third["top1"]["id"] != third["id"]
    assert third["nearest_same_role"]["distance"] == pytest.approx(0.4, abs=1e-3)
    assert report["models"][MODELS[0]]["distances"]["same_role_pairs"] == 4
    assert report["models"][MODELS[0]]["distances"]["other_role_pairs"] == 6
    assert report["models"][MODELS[0]]["distances"]["pair_auc"] == 1.0
    assert report["models"][MODELS[0]]["grouping"] is None
    assert len(read_json(out / f"pairs-{MODELS[1]}.json")) == 10
    examples = report["examples"]
    assert examples["far_same_role"][0]["distance"] == pytest.approx(0.4, abs=1e-3)
    assert set(examples["far_same_role"][0]["distances"]) == set(MODELS)
    assert examples["wrong_top1"] == []
    wavs = sorted(out.glob("examples/*/*/*.wav"))
    assert len(wavs) == 2 * (len(examples["far_same_role"]) + len(examples["near_other_role"]))
    assert sf.info(str(wavs[0])).samplerate == 44100
    with pytest.raises(ValueError, match="已存在"):
        diagnose(episodes, [annotation], MODELS, out)


def test_groups_split_missed_pairs_by_threshold_and_must_match_segments(tmp_path: Path) -> None:
    episodes, annotation = _fixture(tmp_path)
    ids = [r["id"] for d in episodes for r in read_json(d / "segments.json")]
    groups = tmp_path / "groups.json"
    data = {
        "schema": "avs.groups.v1",
        "threshold": 0.5,
        "episodes": {d.name: {"segments_sha256": digest(d / "segments.json")} for d in episodes},
        "assignments": [
            {"id": i, "speaker": s}
            for i, s in zip(ids, ["g1", "g1", "g2", "g3", "g3", None], strict=True)
        ],
    }
    write_json(groups, data)
    report = diagnose(
        episodes, [annotation, tmp_path / "truth2.json"], MODELS[:1], tmp_path / "d", groups
    )
    grouping = report["models"][MODELS[0]]["grouping"]
    assert grouping["missed_same_role_pairs"] == 2
    assert grouping["missed_within_threshold"] == 2
    assert grouping["false_merged_pairs"] == 0
    assert report["models"][MODELS[0]]["retrieval"]["wrong_top1_in_same_group"] == 0
    data["episodes"]["ep1"]["segments_sha256"] = "stale"
    write_json(groups, data)
    with pytest.raises(ValueError, match="不一致"):
        diagnose(episodes, [annotation], MODELS[:1], tmp_path / "e", groups)


def test_single_label_roles_are_distractors_not_queries(tmp_path: Path) -> None:
    episodes, annotation = _fixture(tmp_path)
    write_json(
        tmp_path / "truth2.json",
        {"source": "ep2.wav", "clips": [{"start": 0, "end": 1, "name": "B"}]},
    )
    report = diagnose(episodes, [annotation, tmp_path / "truth2.json"], MODELS[:1], tmp_path / "d")
    assert report["pool"]["single_label_roles"] == ["B"]
    assert report["models"][MODELS[0]]["retrieval"]["queries"] == 3
    assert report["models"][MODELS[0]]["retrieval"]["roles"]["B"]["queries"] == 0
    assert report["models"][MODELS[0]]["distances"]["other_role_pairs"] == 3
    with pytest.raises(ValueError, match="两个角色"):
        diagnose(episodes, [annotation], MODELS[:1], tmp_path / "e")


def test_duration_bins_cover_all_lengths() -> None:
    assert [duration_bin(x) for x in (0.2, 1.5, 4, 60)] == ["0-1.5s", "1.5-3s", "3-6s", ">=6s"]
    with pytest.raises(ValueError):
        duration_bin(-1)
