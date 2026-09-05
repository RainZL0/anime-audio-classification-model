"""三个候选办法本身：给每条片段打一个「这里面像是不止一个人」的分。

分数一律**越高越像是多人片段**，这样它们能放进同一张表比。量它们准不准的代码在
`multi_speaker.py`，两边分开是因为「怎么打分」和「打得准不准」是两件事，将来某个办法
胜出、要搬进管线时，只搬这里的函数就行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

AESTHETICS_DIMS = ("CE", "CU", "PC", "PQ")
"""Audiobox-Aesthetics 给的四项分，都是 1 到 10，越高越好。

它们量的是「一段音频听着怎么样」，不是「里面有几个人」，所以这里全部取负号当分数用：
听着越糟，越可能是多人挤在一起。其中 `PC`（制作复杂度）方向相反 —— 它量的是声音里
成分多不多，多人说话正是成分多，所以 `PC` 不取负。四项各自单列，因为事先不知道哪一项
对得上这件事，猜错了不如四项都摆出来看。
"""


def duration_scores(truth: list[Any]) -> dict[int, float]:
    """对照组：片段越长越算它可疑。不是真办法，是用来揭穿别人的。"""
    return {i: float(t.duration) for i, t in enumerate(truth)}


def squim_scores(quality: Path, truth: list[Any], key: str = "score") -> dict[int, float]:
    """音质分，直接读 probe 留下的 `quality.json`，不重算。

    `key` 可以是 `score`（三项的综合排名）、`stoi`、`pesq`、`sisdr`。全部取负号：音质越差
    越算它可疑。两边的时间戳来自同一次 probe，本该一模一样，所以按毫秒对；万一对不上就跳过，
    并且要当成 bug 去查，不是正常情况。
    """
    import json

    rows = json.loads(quality.read_text(encoding="utf-8"))
    table = {(round(r["start"], 3), round(r["end"], 3)): r for r in rows}

    scores: dict[int, float] = {}
    for i, t in enumerate(truth):
        row = table.get((round(t.start, 3), round(t.end, 3)))
        if row is not None:
            scores[i] = -float(row[key])
    return scores


def aesthetics_scores(
    wav: Path, truth: list[Any], device: str = "cuda"
) -> dict[str, dict[int, float]]:
    """Audiobox-Aesthetics 的四项分，一次跑完全部片段，返回「项目名 -> 分数表」。

    模型是 Meta 拿人打的听感分训练的，第一次跑会从网上拉检查点。它吃 16 kHz 单声道，
    正好就是分析副本，所以直接把波形切片递进去，不落临时文件。
    """
    import numpy as np
    import soundfile as sf
    import torch
    from audiobox_aesthetics.infer import initialize_predictor

    predictor = initialize_predictor()
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    mono = samples[:, 0]

    batch = []
    for t in truth:
        chunk = mono[int(t.start * sample_rate) : int(t.end * sample_rate)]
        wave = torch.from_numpy(np.ascontiguousarray(chunk)).unsqueeze(0)
        batch.append({"path": wave, "sample_rate": sample_rate})

    results = predictor.forward(batch)
    del device  # 预测器自己挑设备，参数留着是为了跟别的打分函数长得一样

    out: dict[str, dict[int, float]] = {}
    for dim in AESTHETICS_DIMS:
        sign = 1.0 if dim == "PC" else -1.0
        out[f"aesthetics_{dim}"] = {i: sign * float(r[dim]) for i, r in enumerate(results)}
    return out


def selfsim_scores(
    wav: Path,
    truth: list[Any],
    model: str = "redimnet2-b6",
    device: str = "cuda",
) -> dict[str, dict[int, float]]:
    """片段内部的声纹一不一致。返回三种读法，各自一张分数表。

    做法：把一条片段切成互相搭一半的小窗口，每个窗口单独算一次声音指纹，再看这些指纹之间
    差多少。如果一条片段里始终是同一个人，几个窗口的指纹应该都指向同一处。

    三种读法量的是不同形状的污染：

    | 代号 | 怎么算 | 想抓什么 |
    | --- | --- | --- |
    | `selfsim_max` | 所有窗口两两之间最大的那个距离 | 任何一处突变 |
    | `selfsim_spread` | 每个窗口到中心的平均距离 | 整条都乱，比如一群人在喊 |
    | `selfsim_drift` | 前半段的中心到后半段中心的距离 | 前一个人说完后一个人接上 |

    窗口按片段长度的三分之一取，夹在 `WINDOW_MIN` 到 `WINDOW_MAX` 之间，所以每条至少能放
    下三个窗口。放不下三个的（太短）不给分，评估时会被排除并记下条数。
    """
    import numpy as np
    import soundfile as sf

    from avs.embeddings.extract import load_extractor
    from avs.evaluation.multi_speaker import WINDOW_MAX, WINDOW_MIN

    extract = load_extractor(model, device)
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    mono = samples[:, 0]

    biggest: dict[int, float] = {}
    spread: dict[int, float] = {}
    drift: dict[int, float] = {}

    for i, t in enumerate(truth):
        window = min(WINDOW_MAX, max(WINDOW_MIN, t.duration / 3))
        hop = window / 2
        starts = np.arange(t.start, t.end - window + 1e-6, hop)
        if len(starts) < 3:
            continue

        vectors = []
        for begin in starts:
            chunk = mono[int(begin * sample_rate) : int((begin + window) * sample_rate)]
            vector = np.asarray(extract(chunk), dtype=np.float64).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vectors.append(vector / norm)
        if len(vectors) < 3:
            continue

        stack = np.stack(vectors)
        distance = 1.0 - stack @ stack.T
        biggest[i] = float(distance.max())

        centre = stack.mean(axis=0)
        centre /= np.linalg.norm(centre)
        spread[i] = float((1.0 - stack @ centre).mean())

        half = len(stack) // 2
        front, back = stack[:half].mean(axis=0), stack[-half:].mean(axis=0)
        front /= np.linalg.norm(front)
        back /= np.linalg.norm(back)
        drift[i] = float(1.0 - front @ back)

    return {"selfsim_max": biggest, "selfsim_spread": spread, "selfsim_drift": drift}
