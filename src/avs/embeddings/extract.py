"""两种可互换的声纹提取器，输入 16 kHz 分析副本，输出单位长度向量。

保留 ReDimNet2 与 WeSpeaker 供身份分组对照，模型差异不能替代人工身份评估。
WeSpeaker 在当前 Windows 环境使用 CPU。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

FRONTIER = "redimnet2-b6"
BASELINE = "wespeaker-resnet293"
ANIME_CHAR = "anime-char"
ANIME_VA = "anime-va"
MODELS = (FRONTIER, BASELINE, ANIME_CHAR, ANIME_VA)

DEFAULT_THRESHOLDS = {FRONTIER: 0.50, BASELINE: 0.60, ANIME_CHAR: 0.53, ANIME_VA: 0.70}
"""每个模型自己的起始距离阈值。相似度尺度因模型而异，套用别人的阈值会扫在毫无意义的一段上。

这些值都是在前两集标签上选的，**而且随片段池增大会漂移**：同一阈值下池子越大，按整组平均距离合并
要求整簇平均距离达标，合并越保守。anime-va 0.70 在 372 条池里 ep03 连回 2613 对、错误合并 76 对，
放进 1176 条池是 2095 对、错误合并 21 对。

**注意这两个数是一起往下走的，所以不是分组变差了，是这个固定数字滑到了取舍曲线的保守那端。**
把错误合并按住不动重新挪分界线，大池子能连上的反而更多（≤76 那一档，2613 对变 3278 对）。
不随池子变的做法见 stages/cluster.py 的 pool_threshold，命令行是 `avs group --relative`；
它还没有独立检验，所以这里仍然是默认。语料继续增长时用 `avs drift` 重新核，别当常数用。"""

ANIME_VARIANTS = {ANIME_CHAR: "char", ANIME_VA: "va"}
"""litagin02/anime_speaker_embedding 的两个变体。char 按角色训练，同一声优配的不同角色也要
分开；va 按声优归并。我们的标签是角色，所以 char 是对口的那个，但两个都留着比：如果 va
反而更好，说明本作里同一声优配多角的情况不多，而声优级别的目标更容易学。

作者提醒这个模型「倾向于积极区分说话人」，同一角色之间的相似度普遍低于其他模型，所以距离分界线不能
从 ReDimNet 那边照搬，必须重新扫。"""

SAMPLE_RATE = 16_000
"""指纹模型都要 16 kHz，也就是分析副本的采样率。别拿原采样率的人声轨喂它们。"""

MIN_SECONDS = 0.5
"""短于这个长度的片段不算声纹，因此进不了分组。

这个值是量出来的，不是猜的。第 3 集标完之后，短于 0.5 秒的片段第一次有了人工身份，
实测它们跟同角色、跟不同角色的相似度几乎分不开：把「同一角色」和「不同角色」两堆配对
排在一起看，短于 0.5 秒的那批排对的比例只有 0.61，而完全随机猜是 0.50。也就是说这些
片段带进来的主要是噪声。0.5 到 1 秒是 0.81，勉强有用，暂时保留。"""

MIN_WINDOW = 0.0
"""喂给模型的最小音频窗口。片段短于它时，向前后两侧对称取原轨上的相邻音频补足，
片段本身的时间范围不变，只是模型多听了一点上下文。0 表示只听片段本身。

**为什么可能有用又可能有害。** 短片段的指纹差，一个解释是模型听到的音太少；补上相邻音频
等于给它更多材料。但相邻音频未必还是同一个人在说，补过头就会把邻座的声音混进来。
是利大于弊还是相反，只能在人工标签上量，别凭直觉定。"""

REDIMNET2_REPO = "PalabraAI/redimnet2"
REDIMNET2_SIZE = "b6"
WESPEAKER_REPO = "Wespeaker/wespeaker-voxceleb-resnet293-LM"
WESPEAKER_ONNX = "voxceleb_resnet293_LM.onnx"
"""pyannote 的加载器默认找的文件名是 `speaker-embedding.onnx`，而这个仓库里叫别的名字，
所以得自己先下下来再把本地路径递给它。"""


@dataclass(frozen=True)
class Embedded:
    """一条片段的指纹。vector 单独存进 .npy，这里只留能读的元信息。"""

    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class Extractor(Protocol):
    """吃一段 16 kHz 单声道波形，吐一串数字。"""

    def __call__(self, mono: Any) -> Any: ...


def _load_redimnet2(device: str) -> Extractor:
    import numpy as np
    import torch

    # torch.hub.load 自己没写类型标注，mypy 会拦，这里放行
    model = torch.hub.load(  # type: ignore[no-untyped-call]
        REDIMNET2_REPO,
        "redimnet2",
        model_name=REDIMNET2_SIZE,
        train_type="lm",
        pretrained=True,
        trust_repo=True,
    )
    model = model.to(device).eval()

    def extract(mono: Any) -> Any:
        wave = torch.from_numpy(np.ascontiguousarray(mono)).unsqueeze(0).to(device)
        with torch.no_grad():
            return model(wave).squeeze(0).cpu().numpy()

    return extract


def _load_wespeaker(device: str) -> Extractor:
    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

    onnx = hf_hub_download(repo_id=WESPEAKER_REPO, filename=WESPEAKER_ONNX)
    # onnxruntime-gpu 在本机是坏的，别把 cuda 递进去，见模块开头第 2 条
    model = PretrainedSpeakerEmbedding(onnx, device=torch.device("cpu"))

    def extract(mono: Any) -> Any:
        # pyannote 要 (批, 声道, 采样点) 三维
        wave = torch.from_numpy(np.ascontiguousarray(mono))[None, None, :]
        return np.asarray(model(wave)).squeeze(0)

    return extract


def load_extractor(model: str, device: str = "cuda") -> Extractor:
    """按代号载入一个指纹模型。device 对 wespeaker 不生效，理由见模块开头。"""
    if model == FRONTIER:
        return _load_redimnet2(device)
    if model == BASELINE:
        return _load_wespeaker(device)
    if model in ANIME_VARIANTS:
        return _load_anime(ANIME_VARIANTS[model], device)
    raise ValueError(f"不认识的模型 {model!r}，只能是 {' 或 '.join(MODELS)}")


def _load_anime(variant: str, device: str) -> Extractor:
    """动画域的 ECAPA-TDNN。包里的 get_embedding 只收文件路径，这里照它的做法直接喂数组，
    省掉每条片段写一个临时文件。输入同样是 16 kHz 单声道，正好是分析副本。"""
    import numpy as np
    import torch
    from anime_speaker_embedding import AnimeSpeakerEmbedding

    model = AnimeSpeakerEmbedding(variant=variant, device=device)

    def extract(mono: Any) -> Any:
        wave = torch.from_numpy(np.ascontiguousarray(mono)).float().unsqueeze(0).to(device)
        with torch.inference_mode():
            vector = model(wave).squeeze(0).squeeze(0)
            return torch.nn.functional.normalize(vector, dim=0).cpu().numpy()

    return extract


def embed_segments(
    wav: Path,
    segments: list[Any],
    model: str = FRONTIER,
    device: str = "cuda",
    window: float = MIN_WINDOW,
) -> tuple[list[Embedded], Any]:
    """给每条片段算指纹。wav 要 16 kHz 单声道，也就是分析副本。

    `window` 是最小听音窗口，短片段会对称地向两边借相邻音频补到这个长度；元信息里记的
    仍是片段自己的时间范围，借来的部分只影响模型听到什么，不影响这条片段是什么。

    返回（元信息列表, 指纹矩阵）。矩阵每行一条，行号跟列表对齐，已经做过长度归一，
    所以两行点乘就是余弦相似度。
    """
    import numpy as np
    import soundfile as sf

    extract = load_extractor(model, device)
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=True)
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"{wav} 是 {sample_rate} Hz，指纹模型要 {SAMPLE_RATE} Hz 的分析副本")
    mono = samples[:, 0]

    meta: list[Embedded] = []
    vectors: list[Any] = []
    for seg in segments:
        start, end = float(seg["start"]), float(seg["end"])
        if end - start < MIN_SECONDS:
            continue
        heard = _window(start, end, window, len(mono) / sample_rate)
        chunk = mono[int(heard[0] * sample_rate) : int(heard[1] * sample_rate)]
        vector = np.asarray(extract(chunk), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        meta.append(Embedded(speaker=str(seg.get("speaker", "")), start=start, end=end))
        vectors.append(vector / norm)

    if not vectors:
        raise RuntimeError("一条指纹都没算出来，检查片段时长和分析副本")
    return meta, np.stack(vectors)


def _window(start: float, end: float, window: float, duration: float) -> tuple[float, float]:
    """把不足 `window` 的片段对称扩到 `window`；碰到轨道两端就往另一侧补回来。"""
    if window <= 0 or end - start >= window:
        return start, end
    room = (window - (end - start)) / 2
    low, high = start - room, end + room
    if low < 0:
        low, high = 0.0, min(duration, high - low)
    if high > duration:
        low, high = max(0.0, low - (high - duration)), duration
    return low, high
