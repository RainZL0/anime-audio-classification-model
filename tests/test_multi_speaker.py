"""量「多人片段检测」那把尺子本身对不对。

这里不碰模型，只造几条假数据喂给评分函数。要防住的是一类很容易犯的错：尺子坏了却还给出
好看的数字，那样会让人拿错误的结论去做决定。
"""

from __future__ import annotations

import json
from pathlib import Path

from avs.evaluation.multi_speaker import (
    Truth,
    _auc,
    _auc_length_matched,
    _catch_rate,
    evaluate,
    load_truth,
)


def _truth(*rows: tuple[float, str]) -> list[Truth]:
    """按（时长, 名字）造片段，首尾接着排。"""
    clips = []
    clock = 0.0
    for duration, name in rows:
        clips.append(Truth(start=clock, end=clock + duration, name=name))
        clock += duration + 1.0
    return clips


def test_load_truth_drops_the_undecidable(tmp_path: Path) -> None:
    """「听不清」和「不是说话」既不算多人也不算单人，必须扔掉，留着会污染分数。"""
    path = tmp_path / "ann.json"
    path.write_text(
        json.dumps(
            {
                "clips": [
                    {"start": 0.0, "end": 2.0, "name": "teo"},
                    {"start": 3.0, "end": 5.0, "name": "__multiple__"},
                    {"start": 6.0, "end": 8.0, "name": "__unclear__"},
                    {"start": 9.0, "end": 11.0, "name": "__not_speech__"},
                    {"start": 12.0, "end": 14.0, "name": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    truth = load_truth(path)
    assert [t.name for t in truth] == ["teo", "__multiple__"]
    assert [t.is_multiple for t in truth] == [False, True]


def test_auc_reads_the_right_direction() -> None:
    """分数越高越该是多人片段。方向反了整张表都会读反，所以钉死。"""
    flag = [True, True, False, False]
    assert _auc([1.0, 1.0, 0.0, 0.0], flag) == 1.0
    assert _auc([0.0, 0.0, 1.0, 1.0], flag) == 0.0
    assert _auc([1.0, 1.0, 1.0, 1.0], flag) == 0.5


def test_length_matching_kills_the_duration_shortcut() -> None:
    """只看时长的「办法」必须在配平之后掉到瞎猜的水平，否则这个控制是白做的。

    造的数据里多人片段全都更长，所以不配平时时长能拿满分。配平之后长度接近的一多一单
    时长几乎一样，就分不出高下了。
    """
    truth = _truth((6.0, "__multiple__"), (5.5, "__multiple__"), (5.4, "a"), (2.0, "b"))
    durations = [t.duration for t in truth]
    flag = [t.is_multiple for t in truth]

    assert _auc(durations, flag) == 1.0
    matched, pairs = _auc_length_matched(durations, flag, durations)
    assert pairs == 2  # 2 秒那条跟谁都差太远，配不上对
    assert matched == 1.0  # 6.0 和 5.5 仍然大于 5.4，这里量的是「配平之后还剩多少信号」


def test_length_matching_only_compares_similar_lengths() -> None:
    """长度差得太多的一对不该参与比较，不然这个控制形同虚设。"""
    truth = _truth((10.0, "__multiple__"), (1.0, "a"))
    durations = [t.duration for t in truth]
    matched, pairs = _auc_length_matched(durations, [True, False], durations)
    assert pairs == 0
    assert matched != matched  # 没有可比的对，结果是 nan


def test_catch_rate_counts_what_the_filter_would_remove() -> None:
    """砍掉分数最高的一半，应该正好报出这一半里有多少条多人片段。"""
    flag = [True, True, False, False]
    assert _catch_rate([9.0, 8.0, 1.0, 0.0], flag, 0.5) == 1.0
    assert _catch_rate([1.0, 0.0, 9.0, 8.0], flag, 0.5) == 0.0


def test_evaluate_reports_the_clips_it_could_not_score() -> None:
    """算不出分的片段要被记下来，不能悄悄消失 —— 少了几条会改变结论怎么读。"""
    truth = _truth((5.0, "__multiple__"), (4.5, "a"), (4.4, "b"), (1.0, "c"))
    row = evaluate("假的", {0: 1.0, 1: 0.0, 2: 0.0}, truth)
    assert row["scored"] == 3
    assert row["skipped"] == 1
    assert row["multiple"] == 1
    assert row["single"] == 2
    assert row["auc"] == 1.0
