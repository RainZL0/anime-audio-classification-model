from pathlib import Path

import numpy as np
import pytest

from avs.evaluation.compare import compare
from avs.project import cache_signature, read_json, write_json
from tests.test_pipeline import episode


def test_compare_matches_clip_ids_despite_different_cache_order(tmp_path: Path) -> None:
    directory = episode(tmp_path, "ep1")
    first = directory / "embeddings/redimnet2-b6"
    second = directory / "embeddings/wespeaker-resnet293"
    second.mkdir()
    records = read_json(first / "metadata.json")
    np.save(second / "vectors.npy", np.load(first / "vectors.npy")[::-1])
    write_json(second / "metadata.json", records[::-1])
    write_json(second / "cache.json", cache_signature(directory, "wespeaker-resnet293"))
    annotation = tmp_path / "truth.json"
    write_json(
        annotation,
        {
            "source": "ep1.wav",
            "clips": [dict(records[0], name="A"), dict(records[1], name="B")],
        },
    )
    models = ["redimnet2-b6", "wespeaker-resnet293"]
    out = tmp_path / "comparison.json"
    report = compare([directory], [annotation], models, [0.5, 1.5], out)
    assert [r["false_merged_pairs"] for r in report["results"]] == [0, 1, 0, 1]
    assert report["frontier"] == [
        {"model": m, "method": "average", "threshold": 0.5} for m in models
    ]
    assert all(r["labeled_clips"] == 2 for r in report["results"])
    with pytest.raises(ValueError, match="已存在"):
        compare([directory], [annotation], models, [0.5], out)

    np.save(second / "vectors.npy", np.load(first / "vectors.npy")[:1])
    write_json(second / "metadata.json", records[:1])
    with pytest.raises(ValueError, match="覆盖的片段不同"):
        compare([directory], [annotation], models, [0.5], tmp_path / "bad.json")
