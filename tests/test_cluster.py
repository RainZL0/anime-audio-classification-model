"""分组那一步的测试。

**这里防的头号风险，是刚刚真的踩到过的那个**：拿片段级的分界线去比中心点。中心点是几十条
片段的平均，天然比单条片段互相更近，同一个数字搬过来会把所有人并成一堆 —— 实测拿 0.6 分，
23 个机器分组塌成 2 个人。程序不会报错，只会给出一个看着像模像样的错答案。
"""

from __future__ import annotations

import numpy as np

from avs.stages.cluster import THRESHOLD, Group, assign, centroids, collect, link, summarize


class Meta:
    """长得跟 `embeddings.extract.Embedded` 一样，够这些测试用。"""

    def __init__(self, speaker: str, start: float, end: float) -> None:
        self.speaker, self.start, self.end = speaker, start, end


def _unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float64)
    return vector / np.linalg.norm(vector)


def test_clips_are_grouped_by_episode_and_local_label() -> None:
    """同名的机器分组在不同集里是两个组，不能混为一谈。"""
    runs = [
        ("ep01", [Meta("SPEAKER_00", 0.0, 2.0), Meta("SPEAKER_00", 5.0, 7.0)], np.eye(2)),
        ("ep02", [Meta("SPEAKER_00", 0.0, 3.0)], np.eye(1)),
    ]
    groups = collect(runs)
    assert [(g.episode, g.local, len(g.clips)) for g in groups] == [
        ("ep01", "SPEAKER_00", 2),
        ("ep02", "SPEAKER_00", 1),
    ]


def test_centroid_leans_toward_the_longer_clip() -> None:
    """中心点按时长加权，因为长片段的指纹更可靠。"""
    runs = [
        (
            "ep01",
            [Meta("A", 0.0, 9.0), Meta("A", 10.0, 11.0)],
            np.stack([_unit(1.0, 0.0), _unit(0.0, 1.0)]),
        )
    ]
    point = centroids(collect(runs), runs)[0]
    assert point[0] > point[1]  # 9 秒那条说了算
    assert abs(np.linalg.norm(point) - 1.0) < 1e-9  # 仍然是单位长度


def test_close_points_merge_and_distant_ones_do_not() -> None:
    """够像的并到一起，不够像的分开。这是这一步的全部工作。"""
    points = np.stack([_unit(1.0, 0.0), _unit(1.0, 0.05), _unit(0.0, 1.0)])
    labels = link(points, threshold=0.4)
    assert labels[0] == labels[1]
    assert labels[0] != labels[2]


def test_a_loose_threshold_collapses_everyone_into_one() -> None:
    """分界线放太松会把所有人并成一个。

    这不是假想的失败：拿片段级的 0.6 去比中心点，真的把 23 个机器分组并成了 2 个人。
    程序不报错，所以只能靠测试和人工核对把它挡住。
    """
    points = np.stack([_unit(1.0, 0.0), _unit(0.0, 1.0), _unit(-1.0, 0.2)])
    assert len(set(link(points, threshold=0.4))) == 3
    assert len(set(link(points, threshold=1.5))) == 1


def test_the_default_threshold_is_the_centroid_one() -> None:
    """默认值必须是中心点那把尺子（0.4），不是片段那把（0.6）。"""
    assert THRESHOLD == 0.4


def test_small_groups_go_to_misc() -> None:
    """总时长不够的组并进 _misc，不去费劲区分路人（决策 10）。"""
    big = Group("ep01", "A", [])
    small = Group("ep01", "B", [])
    runs = [
        (
            "ep01",
            [Meta("A", 0.0, 100.0), Meta("B", 200.0, 205.0)],
            np.stack([_unit(1.0, 0.0), _unit(0.0, 1.0)]),
        )
    ]
    groups = collect(runs)
    assigned = assign(groups, np.array([0, 1]), misc_seconds=60.0)
    assert set(assigned) == {"speaker_01", "_misc"}
    assert assigned["speaker_01"][0].duration == 100.0
    assert assigned["_misc"][0].duration == 5.0
    del big, small


def test_speakers_are_numbered_by_how_much_material_they_have() -> None:
    """speaker_01 是素材最多的那个，方便一眼看出主角。"""
    runs = [
        (
            "ep01",
            [Meta("A", 0.0, 70.0), Meta("B", 100.0, 300.0)],
            np.stack([_unit(1.0, 0.0), _unit(0.0, 1.0)]),
        )
    ]
    assigned = assign(collect(runs), np.array([0, 1]))
    assert assigned["speaker_01"][0].duration == 200.0
    assert assigned["speaker_02"][0].duration == 70.0


def test_summary_says_which_episodes_a_speaker_came_from() -> None:
    """一个组是不是真的跨集连上了，要能一眼看出来。"""
    runs = [
        ("ep01", [Meta("A", 0.0, 80.0)], np.stack([_unit(1.0, 0.0)])),
        ("ep02", [Meta("C", 0.0, 80.0)], np.stack([_unit(1.0, 0.01)])),
    ]
    groups = collect(runs)
    assigned = assign(groups, np.array([0, 0]))
    report = summarize(assigned, groups)
    assert report["speakers_out"] == 1
    assert report["speakers"][0]["episodes"] == ["ep01", "ep02"]
