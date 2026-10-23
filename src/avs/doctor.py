"""Check the machine before the first episode: GPU, FFmpeg, the voice separation model, the
Hugging Face token and free disk space. `avs doctor` prints these, and the interface's welcome page
shows the same list."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from avs.language import say

FREE_GB = 5
"""Warn below this much free disk space. One processed episode takes about 0.5 GB."""


@dataclass(frozen=True)
class Check:
    ok: bool
    text: str
    fix: str = ""
    """What to do when `ok` is false."""
    required: bool = True
    """False means the tool still works without it, only slower or with one feature less."""


def checks(where: Path) -> list[Check]:
    """`where` is the folder whose disk is checked for free space."""
    import torch

    from avs.audio import SEPARATION_MODEL
    from avs.pipeline import TOKEN_HOWTO, has_hf_token

    cuda = torch.cuda.is_available()
    gpu = f", {torch.cuda.get_device_name(0)}" if cuda else ""
    found = [
        Check(
            cuda,
            say(
                f"torch {torch.__version__}，CUDA {'可用' if cuda else '不可用'}{gpu}",
                f"torch {torch.__version__}, CUDA {'available' if cuda else 'not available'}{gpu}",
            ),
            say(
                "没找到能用的 NVIDIA 显卡，会用 CPU。能用，但分离一集的人声会慢很多",
                "No usable NVIDIA GPU was found, so the CPU will be used. It works, but separating "
                "vocals for one episode is much slower",
            ),
            required=False,
        )
    ]
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        found.append(
            Check(
                bool(path),
                f"{tool}: {path or say('没找到', 'not found')}",
                say(
                    "装上 FFmpeg，把它的 bin 文件夹加进 PATH，再重启 avs",
                    "Install FFmpeg, add its bin folder to PATH, and restart avs",
                ),
            )
        )
    model = Path("models") / SEPARATION_MODEL
    found.append(
        Check(
            True,
            say(f"人声分离模型：{model}", f"Voice separation model: {model}")
            if model.exists()
            else say(
                "人声分离模型：第一次用到时自动下载",
                "Voice separation model: will be downloaded automatically the first time it is "
                "used",
            ),
        )
    )
    token = has_hf_token()
    found.append(
        Check(
            token,
            say(
                f"Hugging Face 令牌：{'有' if token else '没有'}",
                f"Hugging Face token: {'present' if token else 'missing'}",
            ),
            say(
                "只有不填字幕偏移、要自动测的时候才需要：",
                "Only needed when the subtitle offset is not given and should be measured "
                "automatically: ",
            )
            + str(TOKEN_HOWTO),
            required=False,
        )
    )
    free = shutil.disk_usage(where).free / 2**30
    found.append(
        Check(
            free >= FREE_GB,
            say(
                f"{where} 所在磁盘剩余 {free:.0f} GB",
                f"Free space on the disk of {where}: {free:.0f} GB",
            ),
            say(
                "处理好的一集大约占 0.5 GB，留够空间",
                "One processed episode takes about 0.5 GB, so leave enough space",
            ),
        )
    )
    return found
