"""Cut the short video pieces the interface plays next to each line."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

VIDEO_PAD = 0.5
"""Seconds to keep before and after each video cut. The dialogue line alone often does not show who
is speaking, so some context is needed."""
VIDEO_HEIGHT = 360
"""Height of the exported picture. Tall enough to see who is speaking. Smaller means faster cutting
and loading."""


def cut_video(video: Path, start: float, end: float, out: Path) -> None:
    """Cut a short piece of video with ffmpeg and convert it to H.264 mp4, which browsers can always
    play.

    The source is HEVC, and browser support for it depends on the browser version, so it cannot be
    relied on. So this always transcodes, and also scales the picture down to `VIDEO_HEIGHT`.
    In measurements, a 2-3 second clip is cut in under half a second, so clips are cut on demand
    rather than all in advance.
    `-ss` goes before `-i` for fast seeking. Without this, every cut would decode from the start.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    # The process number keeps two apps open on the same project from writing into one file.
    temporary = out.with_suffix(f".{os.getpid()}.part.mp4")
    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.05, end - start):.3f}",
        "-i", str(video),
        "-vf", f"scale=-2:{VIDEO_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", "-y", str(temporary),
    ]  # fmt: skip
    try:
        subprocess.run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            f"Video cut failed. Check that ffmpeg is available and the video can be read: {exc}"
        ) from exc
    temporary.replace(out)
