"""Check the machine before the first episode: the operating system, GPU, FFmpeg, the voice
separation model, the Hugging Face token and free disk space. `avoc doctor` prints these, and the
interface's welcome page shows the same list."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from avoc.language import Words, say

FREE_GB = 5
"""Warn below this much free disk space. One processed episode takes about 0.5 GB."""

FFMPEG_HOWTO = Words(
    "装上 FFmpeg。推荐用 Scoop：在 PowerShell 里运行 scoop install ffmpeg；"
    "还没有 Scoop 的话，先运行 "
    "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser 和 "
    "Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression 装上它（见 https://scoop.sh）。"
    "也可以从 https://ffmpeg.org/download.html 下载 Windows 版，解压后把里面的 bin 文件夹加进 PATH "
    "环境变量。装好后关掉终端、新开一个，再启动 avoc",
    "Install FFmpeg. Scoop is the easiest: run scoop install ffmpeg in PowerShell. Without Scoop, "
    "first install it by running Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope "
    "CurrentUser and Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression (see "
    "https://scoop.sh). Or download the Windows build from https://ffmpeg.org/download.html, unzip "
    "it and add its bin folder to the PATH environment variable. Then close the terminal, open a "
    "new one, and start avoc again",
)
"""What to do when FFmpeg is missing on Windows."""

FFMPEG_HOWTO_MAC = Words(
    "装上 FFmpeg：用 Homebrew 运行 brew install ffmpeg。还没有 Homebrew 的话，先按 https://brew.sh "
    "上的那一行命令装上它",
    "Install FFmpeg with Homebrew: brew install ffmpeg. Without Homebrew, first install it with "
    "the one command on https://brew.sh",
)

FFMPEG_HOWTO_LINUX = Words(
    "用系统的包管理器装上 FFmpeg，比如 Ubuntu 或 Debian：sudo apt install ffmpeg；"
    "Fedora：sudo dnf install ffmpeg-free；Arch：sudo pacman -S ffmpeg",
    "Install FFmpeg with your system's package manager, for example on Ubuntu or Debian: "
    "sudo apt install ffmpeg; Fedora: sudo dnf install ffmpeg-free; Arch: sudo pacman -S ffmpeg",
)


def ffmpeg_howto() -> str:
    """What to do when FFmpeg is missing, on this system. Also said when the add form or `avoc add`
    finds no FFmpeg."""
    if sys.platform == "darwin":
        return str(FFMPEG_HOWTO_MAC)
    if sys.platform.startswith("linux"):
        return str(FFMPEG_HOWTO_LINUX)
    return str(FFMPEG_HOWTO)


def system_name() -> str:
    """The operating system and its version, as people know it: "Windows 11 (10.0.26100)"."""
    import platform

    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.version()})"
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    try:
        return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    except OSError:
        return f"{platform.system()} {platform.release()}"


@dataclass(frozen=True)
class Check:
    ok: bool
    text: str
    fix: str = ""
    """What to do when `ok` is false."""
    required: bool = True
    """False means the tool still works without it, only slower or with one feature less."""
    topic: str = ""
    """A fixed name for checks the interface shows in their own way: "system" (a question mark
    rather than a cross, as other systems are untested, not broken), "token", "ffmpeg"."""
    can_install: bool = False
    """The interface can fix it with one click: FFmpeg on Windows, through install_ffmpeg.ps1."""


def install_ffmpeg() -> tuple[bool, str]:
    """Run install_ffmpeg.ps1, Windows only. On success its folder goes on this process's PATH, so
    FFmpeg works at once without restarting avoc. Returns whether it worked and what it printed."""
    import os
    import subprocess

    script = Path(__file__).with_name("install_ffmpeg.ps1")
    try:
        done = subprocess.run(
            [
                *("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"),
                *("-File", str(script)),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30 * 60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (done.stdout + done.stderr).strip()
    shims = next(
        (line[6:] for line in reversed(output.splitlines()) if line.startswith("SHIMS=")), None
    )
    if done.returncode or not shims:
        return False, output
    os.environ["PATH"] = shims + os.pathsep + os.environ.get("PATH", "")
    return bool(shutil.which("ffmpeg")), output


def checks(where: Path) -> list[Check]:
    """`where` is the folder whose disk is checked for free space."""
    import torch

    from avoc.audio import MODELS_DIR, SEPARATION_MODEL
    from avoc.pipeline import TOKEN_HOWTO, has_hf_token

    cuda = torch.cuda.is_available()
    gpu = f", {torch.cuda.get_device_name(0)}" if cuda else ""
    windows = sys.platform == "win32"
    found = [
        Check(
            windows,
            say(f"系统：{system_name()}", f"System: {system_name()}"),
            say(
                "avoc 主要在 Windows 上测试。在这个系统上大多也能用，但可能遇到没测到的问题",
                "avoc is mainly tested on Windows. It mostly works on this system too, but you "
                "may meet problems no one has tested",
            ),
            required=False,
            topic="system",
        ),
        Check(
            cuda,
            say(
                f"torch {torch.__version__}，CUDA {'可用' if cuda else '不可用'}{gpu}",
                f"torch {torch.__version__}, CUDA {'available' if cuda else 'not available'}{gpu}",
            ),
            say(
                "没找到能用的 NVIDIA 显卡，会用 CPU：能用，但每集要慢很多。有 NVIDIA 显卡的话，"
                "从 https://www.nvidia.com/drivers 更新显卡驱动，再重启 avoc",
                "No usable NVIDIA GPU was found, so the CPU will be used: it works, but each "
                "episode takes much longer. If you have an NVIDIA card, update its driver from "
                "https://www.nvidia.com/drivers and restart avoc",
            ),
            required=False,
        ),
    ]
    # One line for both: ffprobe always comes with ffmpeg.
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    ffmpeg_folder = Path(shutil.which("ffmpeg") or "").parent
    found.append(
        Check(
            not missing,
            say(
                f"FFmpeg：没找到 {' 和 '.join(missing)}",
                f"FFmpeg: {' and '.join(missing)} not found",
            )
            if missing
            else say(f"FFmpeg：{ffmpeg_folder}", f"FFmpeg: {ffmpeg_folder}"),
            ffmpeg_howto(),
            # The page shows the Windows steps, with the one-click button, in its own box; on other
            # systems the plain text above is enough.
            topic="ffmpeg" if sys.platform == "win32" else "",
            can_install=sys.platform == "win32",
        )
    )
    model = MODELS_DIR / SEPARATION_MODEL
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
            topic="token",
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
                "处理好的一集大约占 0.5 GB。腾出空间，或者把工作文件夹放到空间更多的磁盘上",
                "One processed episode takes about 0.5 GB. Free some space, or put the workspace "
                "on a disk with more room",
            ),
        )
    )
    return found
