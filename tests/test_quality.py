"""音质筛选那两道关的测试。

**这里防的是「筛选规矩有两份，说的话不一样」。** 管线里筛一次（`keep_best`），
`avs embed` 和 `avs label` 又要各自算出「这一集最后留下哪些」（`select_rows`）。
两边算出来的必须是同一批，否则拿来验证的片段跟实际产出的片段就对不上了。
"""

from __future__ import annotations

from avs.stages.quality import (
    MIN_PESQ,
    MIN_SISDR,
    MIN_STOI,
    Quality,
    keep_best,
    passes_floor,
    select_rows,
)


def _q(score: float, stoi: float = 0.99, pesq: float = 4.0, sisdr: float = 25.0) -> Quality:
    return Quality(speaker="A", start=0.0, end=2.0, stoi=stoi, pesq=pesq, sisdr=sisdr, score=score)


def test_keeps_the_best_share() -> None:
    """按分数排名留下前一部分，其余淘汰。"""
    kept, rejected = keep_best([_q(s / 10) for s in range(10)], keep_ratio=0.5)
    assert [q.score for q in kept] == [0.9, 0.8, 0.7, 0.6, 0.5]
    assert len(rejected) == 5


def test_rejected_clips_come_back_instead_of_disappearing() -> None:
    """淘汰的要带回来，万一比例定错了能捞回去。这是 HOW_IT_WORKS 4.7 的规矩。"""
    scored = [_q(s / 10) for s in range(10)]
    kept, rejected = keep_best(scored, keep_ratio=0.3)
    assert len(kept) + len(rejected) == len(scored)


def test_the_floor_bites_even_inside_the_kept_share() -> None:
    """排名靠前但音质绝对值不合格的，照样要淘汰。

    这是绝对下限存在的全部意义：一集整体都差的时候，相对排名照样会留下「最好的」那批废料。
    """
    good = _q(0.9)
    bad = _q(0.8, stoi=MIN_STOI - 0.01, pesq=MIN_PESQ - 0.1, sisdr=MIN_SISDR - 1)
    kept, rejected = keep_best([good, bad], keep_ratio=1.0)
    assert kept == [good]
    assert rejected == [bad]


def test_each_floor_alone_is_enough_to_reject() -> None:
    """三项任意一项不过就淘汰，不是三项都差才淘汰。"""
    assert passes_floor(_q(0.9))
    assert not passes_floor(_q(0.9, stoi=MIN_STOI - 0.01))
    assert not passes_floor(_q(0.9, pesq=MIN_PESQ - 0.1))
    assert not passes_floor(_q(0.9, sisdr=MIN_SISDR - 1))


def test_a_whole_bad_episode_keeps_nothing() -> None:
    """整集都是废料时，要一条都不留，而不是「留下废料里最好的 70%」。"""
    junk = [_q(s / 10, stoi=0.4, pesq=1.1, sisdr=-10.0) for s in range(10)]
    kept, rejected = keep_best(junk)
    assert kept == []
    assert len(rejected) == 10


def test_both_entry_points_pick_the_same_clips() -> None:
    """管线筛出来的，和 embed / label 算出来的，必须是同一批。"""
    scored = [
        _q(0.9),
        _q(0.8, sisdr=MIN_SISDR - 1),
        _q(0.7),
        _q(0.6),
        _q(0.5, pesq=MIN_PESQ - 0.2),
        _q(0.4),
    ]
    kept, _ = keep_best(scored, keep_ratio=0.7)
    rows = select_rows([q.__dict__ for q in scored], keep_ratio=0.7)
    assert [q.score for q in kept] == [r["score"] for r in rows]
