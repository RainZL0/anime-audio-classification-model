"""把每条片段变成一串数字（声音指纹），供后面分组用。

**两个模型都跑，用自己的数据选。** 理由见 `TOOLS.md` 第 2 节：这些模型在公开评测集上已经
卷到很难分高下，而它们全是拿真人说话训练的，到了日语动画配音这个场景，排名完全可能反过来。
所以这里不预设哪个更好，两个都算一遍，拿 `evaluation/distance.py` 的结果来判。

| 代号 | 是什么 | 声纹错误率 | 为什么留着它 |
| --- | --- | --- | --- |
| `redimnet2-b6` | ReDimNet2 B6 | 0.287% | 前沿臂。Interspeech 2026，2026-07-01 发布，
比 ResNet293 错误率低三分之一而参数更少 |
| `wespeaker-resnet293` | WeSpeaker ResNet293-LM | 0.447% | 稳妥臂。用得广，pyannote 生态同源 |

两个数字都在 VoxCeleb1-O 上测，**不代表在动画对白上的排名**，这正是要两个都跑的原因。

两个坑，都会真的碰到：

1. **`torch.hub.load` 会从 GitHub 拉代码并执行它。** ReDimNet2 只有这一种分发方式，没有 pip 包。
   拉的是论文的官方仓库（`PalabraAI/redimnet2`，MIT 许可）。这里显式写了 `trust_repo=True`，
   否则它会在终端里等你敲确认，脚本会一直卡住。
2. **WeSpeaker 那条走的是 onnxruntime，本机的 onnxruntime-gpu 跟 torch 的 CUDA 版本对不上**
   （见 `STATUS.md` 的踩坑记录）。所以它默认按 CPU 跑，90 条片段这个量级几秒钟的事，
   不值得为它去折腾 onnxruntime 的版本。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

FRONTIER = "redimnet2-b6"
BASELINE = "wespeaker-resnet293"
MODELS = (FRONTIER, BASELINE)

SAMPLE_RATE = 16_000
"""指纹模型都要 16 kHz，也就是分析副本的采样率。别拿原采样率的人声轨喂它们。"""

MIN_SECONDS = 1.0
"""短于这个长度的片段指纹不可靠，跳过。见 HOW_IT_WORKS.md 4.5。"""

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
    """按代号载入一个指纹模型。device 只对 redimnet2 生效，理由见模块开头。"""
    if model == FRONTIER:
        return _load_redimnet2(device)
    if model == BASELINE:
        return _load_wespeaker(device)
    raise ValueError(f"不认识的模型 {model!r}，只能是 {' 或 '.join(MODELS)}")


def embed_segments(
    wav: Path,
    segments: list[Any],
    model: str = FRONTIER,
    device: str = "cuda",
) -> tuple[list[Embedded], Any]:
    """给每条片段算指纹。wav 要 16 kHz 单声道，也就是分析副本。

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
        chunk = mono[int(start * sample_rate) : int(end * sample_rate)]
        vector = np.asarray(extract(chunk), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        meta.append(Embedded(speaker=str(seg["speaker"]), start=start, end=end))
        vectors.append(vector / norm)

    if not vectors:
        raise RuntimeError("一条指纹都没算出来，检查片段时长和分析副本")
    return meta, np.stack(vectors)
